"""Anonymous, bounded direct reader for an expressly public Truth Social account.

No sign-in, cookies, CAPTCHA solving, rotating proxies, impersonated browser,
private endpoints, or access-control bypass. Stops/backoffs on access refusal.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Callable

from .config import Config
from .trump_filter import classify_trump_statement
from .event_evidence import assess_truth_evidence
from .media_ocr import extract_image_text, image_url_from_post
from .notifier import notify
from .state import StateStore

ACCOUNT_ID = "107780257626128497"
USERNAME = "realDonaldTrump"
STATUSES_URL = (
    f"https://truthsocial.com/api/v1/accounts/{ACCOUNT_ID}/statuses"
    "?exclude_replies=true&limit=25"
)
MAX_BYTES = 512 * 1024
POST_ID = re.compile(r"^[0-9]{10,24}$")


class DirectUnavailable(RuntimeError):
    def __init__(self, reason: str, *, blocked: bool = False,
                 diagnostic: dict | None = None):
        super().__init__(reason)
        self.blocked = blocked
        self.diagnostic = diagnostic or {}


def _safe_header(value: object, *, limit: int = 100) -> str | None:
    if not isinstance(value, str):
        return None
    # CR/LF must never turn extra response headers into a log field.
    first_line = value.splitlines()[0] if value.splitlines() else ""
    clean = "".join(ch for ch in first_line[:limit] if ch.isascii()
                    and (ch.isalnum() or ch in " .;/=_-"))
    return clean or None


def _classify_denial(status: int, headers, sample: bytes, elapsed_ms: int) -> dict:
    """Return only allowlisted metadata and a coarse reason; never raw HTML."""
    server = _safe_header(headers.get("Server"))
    content_type = _safe_header(headers.get("Content-Type"))
    cf_ray = _safe_header(headers.get("CF-Ray"))
    cf_mitigated = _safe_header(headers.get("cf-mitigated"))
    body = sample.decode("utf-8", errors="replace").lower()
    if cf_mitigated and cf_mitigated.lower() == "challenge":
        reason = "CLOUDFLARE_CHALLENGE"
    elif any(t in body for t in (
        "not available in your country", "not available in your region",
        "unavailable in your country", "unavailable in your region",
        "geographic restriction", "geoblocked", "geo-blocked"
    )):
        reason = "POSSIBLE_GEOGRAPHIC_RESTRICTION"
    elif any(t in body for t in ("error 1020", "error code 1020", "error code: 1020")):
        reason = "CLOUDFLARE_WAF_1020"
    elif status == 401 or (
        content_type and "json" in content_type.lower()
        and any(t in body for t in (
            "authentication required", "unauthorized", "missing token"
        ))
    ):
        reason = "POSSIBLE_AUTHENTICATION_REQUIREMENT"
    elif cf_ray or (server and "cloudflare" in server.lower()):
        reason = "CLOUDFLARE_PRESENT_CAUSE_UNDETERMINED"
    else:
        reason = "ACCESS_DENIED_CAUSE_UNDETERMINED"
    return {
        "http_status": int(status),
        "classification": reason,
        "server": server,
        "content_type": content_type,
        "cf_ray": cf_ray,
        "cf_mitigated": cf_mitigated,
        "elapsed_ms": max(0, int(elapsed_ms)),
        "inspected_body_bytes": len(sample),
    }


class _Text(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, value: str) -> None:
        self.parts.append(value)

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in ("br", "p", "div"):
            self.parts.append(" ")


@dataclass(frozen=True)
class DirectPost:
    post_id: str
    text: str
    published: float
    link: str
    media_only: bool = False
    media_url: str | None = None


@dataclass(frozen=True)
class DirectResult:
    posts: tuple[DirectPost, ...]
    fetched_at: float


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DirectUnavailable("Unexpected redirect; refusing alternate endpoint", blocked=True)


def _published(raw: object) -> float | None:
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None or dt.utcoffset() is None:
        return None
    return dt.astimezone(timezone.utc).timestamp()


def parse_statuses(data: bytes, *, fetched_at: float) -> DirectResult:
    if not data or len(data) > MAX_BYTES:
        raise DirectUnavailable("Empty/oversized public API response")
    try:
        rows = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DirectUnavailable("Public endpoint did not return valid JSON") from exc
    if not isinstance(rows, list):
        raise DirectUnavailable("Public endpoint response is not a statuses array")
    if not rows:
        raise DirectUnavailable("Public endpoint returned no statuses; using RSS fallback")
    if len(rows) > 100:
        raise DirectUnavailable("Unexpected oversized status list")
    output: list[DirectPost] = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        post_id = str(row.get("id") or "")
        account = row.get("account")
        if not POST_ID.fullmatch(post_id):
            continue
        if not isinstance(account, dict):
            continue
        if (str(account.get("id")) != ACCOUNT_ID or
                str(account.get("acct") or account.get("username") or "").casefold()
                != USERNAME.casefold()):
            continue
        if row.get("visibility") != "public":
            continue
        published = _published(row.get("created_at"))
        if published is None or post_id in seen:
            continue
        seen.add(post_id)
        html = row.get("content")
        if not isinstance(html, str):
            continue
        parser = _Text()
        parser.feed(html[:32000])
        text = " ".join("".join(parser.parts).split())[:3000]
        media_only = not text and bool(row.get("media_attachments"))
        if not text and not media_only:
            continue
        # Local canonical URL: never reflect untrusted remote URL into the UI.
        url = f"https://truthsocial.com/@{USERNAME}/{post_id}"
        output.append(DirectPost(
            post_id=post_id, text=text, published=published, link=url,
            media_only=media_only,
            media_url=image_url_from_post(row),
        ))
    if rows and not output:
        raise DirectUnavailable("No statuses passed account identity/content verification")
    return DirectResult(posts=tuple(output), fetched_at=fetched_at)


def fetch_public_statuses(*, timeout: float = 6.0) -> DirectResult:
    """No credentials or browser spoofing. Never retry 401/403/429 internally."""
    headers = {
        "Accept": "application/json",
        "User-Agent": "TradeAlert/0.1 (personal public-status reader)",
        "Cache-Control": "no-cache",
    }
    request = urllib.request.Request(STATUSES_URL, headers=headers)
    opener = urllib.request.build_opener(_NoRedirect)
    started = time.monotonic()
    try:
        with opener.open(request, timeout=timeout) as response:
            data = response.read(MAX_BYTES + 1)
    except urllib.error.HTTPError as exc:
        blocked = exc.code in (401, 403, 429)
        # Bounded inspection; never retain/print the HTTP response body.
        try:
            sample = exc.read(4096)
        except (AttributeError, OSError, ValueError):
            sample = b""
        metadata = _classify_denial(
            exc.code, exc.headers or {}, sample,
            int((time.monotonic() - started) * 1000),
        )
        raise DirectUnavailable(
            f"HTTP {exc.code} from Truth Social public endpoint",
            blocked=blocked, diagnostic=metadata,
        ) from exc
    except DirectUnavailable:
        raise
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise DirectUnavailable(
            f"Public endpoint network error: {type(exc).__name__}"
        ) from exc
    return parse_statuses(data, fetched_at=time.time())


def _relevance(text: str) -> int:
    """Compatibility wrapper for the shared source-scoped classifier."""
    return classify_trump_statement(text).score


async def read_direct_once(config: Config, store: StateStore, *,
                           fetch: Callable = fetch_public_statuses,
                           now: float | None = None, notification=None,
                           alert_callback=None) -> dict:
    """Local hot-path intake, with first-run baseline and per-post dedupe."""
    if not config.truth_direct_enabled:
        return {"status": "DISABLED", "new": 0, "notified": 0}
    result = await asyncio.to_thread(fetch)
    moment = time.time() if now is None else now
    store.set_meta("truth_direct_last_success", datetime.fromtimestamp(
        moment, tz=timezone.utc).isoformat())
    store.set_meta("truth_direct_last_error", "")
    initial = store.get_meta("truth_direct_initialized") is None
    discovered = emitted = notified = media_skipped = 0
    notification = notification or notify
    for post in sorted(result.posts, key=lambda x: x.published):
        key = "TRUTH_PUBLIC:" + post.post_id
        if store.seen(key):
            continue
        discovered += 1
        store.mark_seen(key, at=moment)
        age = moment - post.published
        if initial or age > config.truth_direct_max_age_seconds or age < -120:
            continue
        image_text = ""
        if post.media_url:
            image_text, ocr_status = await asyncio.to_thread(
                extract_image_text, {
                    "media_attachments": [{"type": "image", "url": post.media_url}]
                }
            )
            if ocr_status != "OCR_OK":
                logging.warning("Direct image post %s OCR: %s", post.post_id, ocr_status)
                media_skipped += 1
        elif post.media_only:
            media_skipped += 1
        if not post.text and not image_text:
            continue
        analysis_text = " ".join(x for x in (post.text, image_text) if x)
        evidence = assess_truth_evidence(
            caption=post.text, image_text=image_text, source="DIRECT",
            signal=classify_trump_statement(analysis_text),
        )
        signal = evidence.signal
        score = signal.score
        if score < config.notification_min_score:
            continue
        text = post.text[:450] or "[Ingen inläggstext]"
        ocr_label = ("\n[Bildtext via lokal OCR] " + image_text[:650]) if image_text else ""
        body = (
            f"Trump · {signal.priority} / {signal.category} · Truth Social offentligt inlägg\n"
            f"Evidens: {evidence.event_kind} · EJ KONTROLLERAD\n"
            f"{text}{ocr_label}\n"
            f"Publicerad {datetime.fromtimestamp(post.published).astimezone():%H:%M:%S}"
            f" · upptäckt +{int(max(0, age))} s\n"
            f"Bedömning: {evidence.reason}\n"
            "Ett nytt inlägg är inte bevis på en ny händelse."
        )
        inserted = store.record_alert(
            item_key=key, source="TRUTH_PUBLIC",
            provider="Truth Social public account",
            headline=analysis_text[:240], body=body, score=score,
            published=post.published, link=post.link, at=moment,
        )
        if not inserted:
            continue
        emitted += 1
        if alert_callback:
            try:
                alert_callback(store.unread_alert_count())
            except Exception:
                logging.exception("Direct-source unread callback failed")
        if notification(f"Trade Alert · Trump {signal.priority} · {signal.category}", body):
            notified += 1
        else:
            logging.error("Direct-source alert saved, Windows toast failed: %s", key)
    if initial and result.posts:
        store.set_meta("truth_direct_initialized", datetime.fromtimestamp(
            moment, tz=timezone.utc).isoformat())
    return {
        "status": "BASELINED" if initial and result.posts else "COMPLETE",
        "new": discovered, "alerted": emitted, "notified": notified,
        "media_skipped": media_skipped, "items_returned": len(result.posts),
    }
