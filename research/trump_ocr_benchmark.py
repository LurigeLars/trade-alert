"""One-off reproducible OCR benchmark on verified public Trump post images.

Filenames are kept ephemeral in runner memory. Only metrics and OCR strings
are stored as CI artifacts. No cookies, credentials, proxy or anti-bot bypass.
The source archive contains public post URLs and original-image URLs only.
Accuracy/precision are NOT inferred from OCR-vs-OCR agreement.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps
from trade_alert.media_ocr import (
    MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS, recognize_image_bytes,
    is_approved_image_url,
)
from trade_alert.trump_filter import classify_trump_statement


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise RuntimeError("redirect_not_permitted")


def fetch_public_image(url: str) -> bytes:
    if not is_approved_image_url(url):
        raise ValueError("non_allowlisted_url")
    request = urllib.request.Request(url, headers={
        "Accept": "image/jpeg, image/png, image/webp",
        "User-Agent": "TradeAlertPublicOCRBenchmark/1.0",
    })
    with urllib.request.build_opener(NoRedirect).open(request, timeout=8) as response:
        content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
        if content_type not in ("image/jpeg", "image/png", "image/webp"):
            raise ValueError("unsupported_content_type")
        size = int(response.headers.get("Content-Length") or "0")
        if size > MAX_IMAGE_BYTES:
            raise ValueError("image_too_large")
        blob = response.read(MAX_IMAGE_BYTES + 1)
    if not 1 <= len(blob) <= MAX_IMAGE_BYTES:
        raise ValueError("image_size_invalid")
    return blob


def old_ocr(data: bytes) -> str:
    with Image.open(io.BytesIO(data)) as image:
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ValueError("too_many_pixels")
        image.thumbnail((2000, 2000))
        output = io.BytesIO()
        image.convert("RGB").save(output, "PNG")
    p = subprocess.run(
        ["tesseract", "stdin", "stdout", "-l", "eng", "--psm", "11"],
        input=output.getvalue(), capture_output=True, timeout=6, check=False,
    )
    if p.returncode:
        raise RuntimeError("old_tesseract_failed")
    return " ".join(p.stdout.decode("utf-8", "replace").split())[:4000]


def words(text: str) -> int:
    return len(re.findall(r"\b[A-Za-z]{3,}\b", text))


def metrics(rows: list[dict]) -> dict:
    ok = [r for r in rows if r["status"] == "OK"]
    old_hits = [r for r in ok if r["old_ocr_score"] >= 2]
    new_hits = [r for r in ok if r["new_ocr_score"] >= 2]
    old_post_hits = [r for r in ok if r["old_post_score"] >= 2]
    new_post_hits = [r for r in ok if r["new_post_score"] >= 2]
    changed = [r for r in ok if (r["new_post_score"] >= 2) != (r["old_post_score"] >= 2)]
    old_sec = [r["old_seconds"] for r in ok]
    new_sec = [r["new_seconds"] for r in ok]
    def percentile(values, p):
        if not values: return None
        v = sorted(values)
        return round(v[min(len(v)-1, int(p*(len(v)-1)))], 3)
    return {
        "requested_images": len(rows),
        "downloaded_and_ocr_compared": len(ok),
        "download_or_ocr_failure": len(rows)-len(ok),
        "old_nonblank_ocr": sum(bool(x["old_ocr_text"]) for x in ok),
        "new_nonblank_ocr": sum(bool(x["new_ocr_text"]) for x in ok),
        "old_image_only_market_hits": len(old_hits),
        "new_image_only_market_hits": len(new_hits),
        "new_only_image_market_hits": [
            x["ordinal"] for x in ok if x["old_ocr_score"] < 2 <= x["new_ocr_score"]
        ],
        "lost_image_market_hits": [
            x["ordinal"] for x in ok if x["new_ocr_score"] < 2 <= x["old_ocr_score"]
        ],
        "old_caption_plus_image_market_hits": len(old_post_hits),
        "new_caption_plus_image_market_hits": len(new_post_hits),
        "changed_caption_plus_image_hits": [
            {"ordinal":x["ordinal"],"old":x["old_post_score"],
             "new":x["new_post_score"]} for x in changed
        ],
        "higher_recognized_alpha_word_count": sum(
            x["new_alpha_words"] > x["old_alpha_words"] for x in ok
        ),
        "lower_recognized_alpha_word_count": sum(
            x["new_alpha_words"] < x["old_alpha_words"] for x in ok
        ),
        "median_old_seconds":round(statistics.median(old_sec),3) if ok else None,
        "median_new_seconds":round(statistics.median(new_sec),3) if ok else None,
        "p95_old_seconds":percentile(old_sec,.95),
        "p95_new_seconds":percentile(new_sec,.95),
        "total_download_bytes":sum(x["bytes"] for x in ok),
        "accuracy_requires_independent_human_transcription":True,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset",required=True)
    parser.add_argument("--output",required=True)
    args=parser.parse_args()
    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    posts = dataset["images"]
    if len(posts) != 50 or len({p["media_id"] for p in posts}) != 50:
        raise SystemExit("Benchmark requires exactly 50 distinct images")
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True,exist_ok=True)
    report=[]
    for item in posts:
        record={k:item[k] for k in (
            "ordinal","post_id","media_id","published","post_url","image_url"
        )}
        record["status"]="ERROR"
        try:
            data=fetch_public_image(item["image_url"])
            record["bytes"]=len(data)
            began=time.perf_counter()
            earlier=old_ocr(data)
            record["old_seconds"]=round(time.perf_counter()-began,3)
            began=time.perf_counter()
            newer=recognize_image_bytes(data,executable="tesseract")
            record["new_seconds"]=round(time.perf_counter()-began,3)
            record["old_ocr_text"]=earlier
            record["new_ocr_text"]=newer
            record["old_alpha_words"]=words(earlier)
            record["new_alpha_words"]=words(newer)
            old_ocr_signal=classify_trump_statement(earlier)
            new_ocr_signal=classify_trump_statement(newer)
            old_signal=classify_trump_statement(item["caption"]+" "+earlier)
            new_signal=classify_trump_statement(item["caption"]+" "+newer)
            record.update({
                "old_ocr_score":old_ocr_signal.score,
                "new_ocr_score":new_ocr_signal.score,
                "old_ocr_category":old_ocr_signal.category,
                "new_ocr_category":new_ocr_signal.category,
                "old_post_score":old_signal.score,
                "new_post_score":new_signal.score,
                "old_post_category":old_signal.category,
                "new_post_category":new_signal.category,
                "status":"OK",
            })
        except Exception as exc:
            # Error type only: never print media bytes or secrets.
            record["error"]=type(exc).__name__+":"+str(exc)[:95]
        report.append(record)
        print(
            f"{record['ordinal']:02d}/50 {record['status']} "
            f"old={record.get('old_ocr_score','-')} "
            f"new={record.get('new_ocr_score','-')} "
            f"caption+old={record.get('old_post_score','-')} "
            f"caption+new={record.get('new_post_score','-')} "
            f"sec={record.get('old_seconds','-')}/{record.get('new_seconds','-')}",
            flush=True,
        )
        # Polite, bounded request pace; do not retry errors by default.
        time.sleep(.3)
    summary = metrics(report)
    result={
        "benchmark_date":"2026-10-09",
        "source":"Truth Social public verified account via local Firecrawl MCP",
        "source_dataset":args.dataset,
        "methods":["old: whole image PSM 11","new: 4-region OCR PSM 11/6/11/6"],
        "note":"Not a labelled OCR accuracy/recall estimate; human transcription required.",
        "summary":summary,"results":report
    }
    out_path.write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding="utf-8")
    print("=== SUMMARY ===",flush=True)
    print(json.dumps(summary,indent=2,ensure_ascii=False),flush=True)
    print("REPORT_PATH="+str(out_path),flush=True)


if __name__=="__main__":
    main()
