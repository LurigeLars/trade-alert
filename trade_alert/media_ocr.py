"""Bounded on-device OCR for public Truth Social image attachments.

No OCR vendor, cloud AI, LLM or paid service. All image URLs must belong
to the public static-assets Truth Social CDN; no arbitrary URLs, redirects,
cookies, saved media or access-control bypass. Tesseract OCR is optional,
but missing OCR is an explicit degraded state, never interpreted as no
market relevance.
"""
from __future__ import annotations

import io
import logging
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_IMAGE_BYTES = 2 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000
MAX_OCR_CHARS = 4000
MAX_URL_LENGTH = 1500
CDN_HOST = re.compile(r"static-assets-[1-9]\.truthsocial\.com\Z", re.IGNORECASE)
ALLOWED_TYPES = frozenset(("image/jpeg", "image/png", "image/webp"))
ALLOWED_FORMATS = frozenset(("JPEG", "PNG", "WEBP"))


class OCRUnavailable(Exception):
    """Local OCR executable is not installed or could not run."""


class OCRFetchFailed(Exception):
    """A bounded media fetch or decode failed; do not claim it has no text."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OCRFetchFailed("Image redirect not allowed")


def is_approved_image_url(value: object) -> bool:
    if not isinstance(value, str) or not 1 <= len(value) <= MAX_URL_LENGTH:
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
    except ValueError:
        return False
    return (
        parsed.scheme == "https" and bool(parsed.hostname)
        and CDN_HOST.fullmatch(parsed.hostname) is not None
        and parsed.port in (None, 443)
        and parsed.username is None and parsed.password is None
        and not parsed.fragment
        and bool(parsed.path) and parsed.path.startswith("/")
    )


def image_url_from_post(row: dict) -> str | None:
    """At most one image per new post, never from HTML or arbitrary links."""
    items = row.get("media_attachments")
    if not isinstance(items, list):
        return None
    for item in items[:2]:
        if not isinstance(item, dict) or item.get("type") != "image":
            continue
        for attr in ("url", "preview_url"):
            url = item.get(attr)
            if is_approved_image_url(url):
                return url
    return None


def tesseract_path() -> str | None:
    """Use an installed Tesseract executable, never download one at runtime."""
    existing = shutil.which("tesseract")
    if existing:
        return existing
    if os.name == "nt":
        for root in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
            if not root:
                continue
            found = Path(root) / "Tesseract-OCR" / "tesseract.exe"
            if found.is_file():
                return str(found)
    return None


def _fetch_image(url: str) -> bytes:
    if not is_approved_image_url(url):
        raise OCRFetchFailed("Image host not approved")
    request = urllib.request.Request(
        url,
        headers={"Accept": "image/jpeg, image/png, image/webp",
                 "User-Agent": "TradeAlertImageOCR/0.1"},
        method="GET",
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=3) as response:
            media_type = response.headers.get("Content-Type", "").split(";")[0].lower()
            if media_type not in ALLOWED_TYPES:
                raise OCRFetchFailed("Unexpected image content type")
            advertised = int(response.headers.get("Content-Length", "0") or "0")
            if advertised > MAX_IMAGE_BYTES:
                raise OCRFetchFailed("Image too large")
            data = response.read(MAX_IMAGE_BYTES + 1)
    except (OSError, ValueError, urllib.error.URLError) as error:
        raise OCRFetchFailed("Image source unavailable") from error
    if not 1 <= len(data) <= MAX_IMAGE_BYTES:
        raise OCRFetchFailed("Image size outside bound")
    return data


def _ocr_png(frame: Image.Image, *, psm: int, executable: str,
             timeout: float) -> subprocess.CompletedProcess[bytes]:
    output = io.BytesIO()
    frame.save(output, format="PNG")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    return subprocess.run(
        [executable, "stdin", "stdout", "-l", "eng", "--psm", str(psm)],
        input=output.getvalue(),
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        timeout=timeout, check=False, creationflags=flags,
    )


def recognize_image_bytes(data: bytes, *, executable: str | None = None) -> str:
    """Combine a layout pass with bounded region passes for poster headlines.

    The default full-image sparse-text layout can skip a large banner
    entirely when pictures and numbers dominate the page. Scan the upper
    quarter separately, then middle and footer. Never assume that a blank
    or low-quality full-image pass proves the image contains no market text.
    """
    executable = tesseract_path() if executable is None else executable
    if not executable:
        raise OCRUnavailable("Tesseract OCR is not installed")
    if not 1 <= len(data) <= MAX_IMAGE_BYTES:
        raise OCRFetchFailed("Image size outside bound")
    try:
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in ALLOWED_FORMATS:
                raise OCRFetchFailed("Unsupported image format")
            width, height = image.size
            if width < 1 or height < 1 or width * height > MAX_IMAGE_PIXELS:
                raise OCRFetchFailed("Image dimensions outside bound")
            image = ImageOps.exif_transpose(image)
            image.thumbnail((2000, 2000))
            # A transparent poster must be composited on white rather than
            # interpreted against a black background by the OCR engine.
            if image.mode in ("RGBA", "LA") or "transparency" in image.info:
                rgba = image.convert("RGBA")
                rgb = Image.new("RGB", image.size, "white")
                rgb.paste(rgba, mask=rgba.getchannel("A"))
            else:
                rgb = image.convert("RGB")
    except (UnidentifiedImageError, ValueError, OSError,
            Image.DecompressionBombError) as exc:
        raise OCRFetchFailed("Invalid image") from exc

    w, h = rgb.size
    # Four deterministic OCR attempts; time budget is shared, not 4 * 6s.
    regions = (
        (rgb, 11),  # full page, sparse text
        (rgb.crop((0, 0, w, max(1, int(h * .26)))), 6),
        (rgb.crop((0, int(h * .25), w, max(1, int(h * .75)))), 11),
        (rgb.crop((0, int(h * .74), w, h)), 6),
    )
    deadline = time.monotonic() + 8.0
    found: list[str] = []
    dedupe: set[str] = set()
    successful = 0
    incomplete = False
    for frame, psm in regions:
        remaining = deadline - time.monotonic()
        if remaining <= .05:
            incomplete = True
            break
        try:
            result = _ocr_png(frame, psm=psm, executable=executable,
                              timeout=min(3.0, remaining))
        except subprocess.TimeoutExpired:
            incomplete = True
            continue
        except (FileNotFoundError, PermissionError, OSError) as exc:
            raise OCRUnavailable("Tesseract OCR could not run") from exc
        if result.returncode != 0:
            incomplete = True
            continue
        successful += 1
        for raw_line in result.stdout.decode("utf-8", "replace").splitlines():
            line = " ".join(raw_line.split())
            if not line:
                continue
            normalized = line.casefold()
            if normalized in dedupe:
                continue
            dedupe.add(normalized)
            found.append(line)
    if successful == 0:
        raise OCRUnavailable("All local OCR passes failed")
    if incomplete:
        logging.warning("Public image OCR partially degraded or timed out")
    return " ".join(found)[:MAX_OCR_CHARS]


def extract_image_text(row: dict) -> tuple[str, str]:
    """Return (image text, status). Never misrepresent OCR errors as negatives."""
    url = image_url_from_post(row)
    if not url:
        return "", "NO_APPROVED_IMAGE"
    if not tesseract_path():
        return "", "OCR_UNAVAILABLE"
    try:
        return recognize_image_bytes(_fetch_image(url)), "OCR_OK"
    except OCRUnavailable:
        logging.warning("Chrome public image OCR unavailable")
        return "", "OCR_UNAVAILABLE"
    except OCRFetchFailed:
        logging.warning("Chrome public image OCR source/format unavailable")
        return "", "OCR_FAILED"


if __name__ == "__main__":
    import argparse

    cli = argparse.ArgumentParser(
        description="Check local OCR or classify a local test image offline"
    )
    cli.add_argument("image", nargs="?", help="local JPEG, PNG or WebP test image")
    args = cli.parse_args()
    print("Local image OCR:", "READY" if tesseract_path() else "UNAVAILABLE")
    if not tesseract_path():
        raise SystemExit("Install Tesseract locally and restart Trade Alert.")
    if args.image:
        file = Path(args.image)
        if not file.is_file() or not 1 <= file.stat().st_size <= MAX_IMAGE_BYTES:
            raise SystemExit("Image missing or exceeds maximum input size")
        from .trump_filter import classify_trump_statement

        ocr_text = recognize_image_bytes(file.read_bytes())
        signal = classify_trump_statement(ocr_text)
        print("OCR-text:", ocr_text)
        print("Prioritet:", signal.priority)
        print("Kategori:", signal.category)
        print("Poäng:", signal.score)
