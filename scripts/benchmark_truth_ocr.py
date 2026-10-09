"""Read-only, local benchmark of public image OCR. Never creates alerts."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from trade_alert.media_ocr import (
    OCRFetchFailed, OCRUnavailable, _fetch_image, is_approved_image_url,
    recognize_image_bytes, tesseract_path,
)
from trade_alert.trump_filter import classify_trump_statement

MANIFEST = ROOT / "tests/data/truthsocial_ocr_unlabelled_20261009.json"
EXPECTED_ACCOUNT = "107780257626128497"


def benchmark(items, *, limit=50, include_secondary=False, delay=1.0,
              fetch=_fetch_image, recognize=recognize_image_bytes,
              classify=classify_trump_statement, sleep=time.sleep):
    """Analyze at most 'limit' unique image contents, with no persistent image bytes.

    The input corpus is *unlabelled*: predictions cannot prove precision/recall.
    Consecutive failed image fetches cause a bounded early stop.
    """
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100")
    if not .5 <= delay <= 5:
        raise ValueError("delay must be between 0.5 and 5 seconds")
    records, hashes = [], set()
    failures_in_row = 0
    stop_reason = "EXHAUSTED"
    for item in items:
        if len(hashes) >= limit:
            stop_reason = "TARGET_REACHED"
            break
        if not include_secondary and item.get("scanner_eligible") is not True:
            continue
        post_id = str(item.get("status_id", ""))
        url = item.get("url")
        result = {"status_id": post_id, "media_id": str(item.get("media_id", "")),
                  "url": url, "scanner_eligible": item.get("scanner_eligible") is True}
        if not post_id.isdecimal() or not is_approved_image_url(url):
            result["status"] = "INVALID_SOURCE"
            records.append(result)
            continue
        try:
            raw = fetch(url)
        except OCRFetchFailed:
            result["status"] = "FETCH_FAILED"
            records.append(result)
            failures_in_row += 1
            if failures_in_row >= 3:
                stop_reason = "FETCH_FAILURE_CIRCUIT_OPEN"
                break
            sleep(delay)
            continue
        failures_in_row = 0
        digest = hashlib.sha256(raw).hexdigest()
        result["sha256"] = digest
        if digest in hashes:
            result["status"] = "DUPLICATE_IMAGE"
            records.append(result)
            sleep(delay)
            continue
        hashes.add(digest)
        started = time.monotonic()
        try:
            text = recognize(raw)
        except OCRUnavailable:
            result["status"] = "OCR_UNAVAILABLE"
            result["ocr_text"] = ""
        except OCRFetchFailed:
            result["status"] = "OCR_FAILED"
            result["ocr_text"] = ""
        else:
            result["status"] = "OCR_OK" if text.strip() else "OCR_EMPTY"
            result["ocr_text"] = text
            signal = classify(text)
            result["priority"] = signal.priority
            result["category"] = signal.category
            result["score"] = signal.score
        result["elapsed_ocr_seconds"] = round(time.monotonic() - started, 3)
        records.append(result)
        sleep(delay)
    counts = Counter(item["status"] for item in records)
    priorities = Counter(item.get("priority", "UNCLASSIFIED")
                         for item in records if item["status"] in ("OCR_OK", "OCR_EMPTY"))
    return {
        "schema_version": 1,
        "run_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "ALL_MEDIA" if include_secondary else "SCANNER_ELIGIBLE_FIRST_IMAGE",
        "requested_unique_images": limit,
        "processed_unique_images": len(hashes),
        "stop_reason": stop_reason,
        "status_counts": dict(counts),
        "priority_counts": dict(priorities),
        "quality_warning": "Unlabelled public images. OCR success is not accuracy; "
                           "precision and recall require manually verified image text "
                           "and relevance labels.",
        "results": records,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--all-media", action="store_true",
                        help="also test later attachments that live scanner ignores")
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not tesseract_path():
        parser.error("Tesseract not installed: install it before attempting network fetches")
    with args.manifest.open(encoding="utf-8") as f:
        source = json.load(f)
    if source.get("account_id") != EXPECTED_ACCOUNT or not isinstance(source.get("items"), list):
        parser.error("manifest must contain the expected public account and image items")
    report = benchmark(source["items"], limit=args.limit,
                       include_secondary=args.all_media, delay=args.delay)
    target = args.output
    if target is None:
        local = Path(os.environ.get("LOCALAPPDATA") or Path.home())
        target = local / "TradeAlert" / "OCR-Benchmarks" / (
            "truthsocial-ocr-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") +
            ".json")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
    print("Result file:", target)
    if report["stop_reason"] == "FETCH_FAILURE_CIRCUIT_OPEN":
        raise SystemExit(2)
    if report["processed_unique_images"] < args.limit:
        raise SystemExit(3)


if __name__ == "__main__":
    main()
