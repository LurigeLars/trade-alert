"""Consume locally queued, untrusted public account posts from Chrome.

Image OCR is local, bounded and limited to static-assets Truth Social CDN.
The same post-ID cursor prevents duplicates between text and image signals.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime
from pathlib import Path

from .config import Config
from .notifier import notify
from .state import StateStore
from .truth_direct import DirectUnavailable, parse_statuses
from .media_ocr import extract_image_text, image_url_from_post
from .trump_filter import classify_trump_statement

POST_FILENAME = re.compile(r"^post-([0-9]{10,24})\.json$")
MAX_FILE_BYTES = 16384
MAX_FILES = 40


def browser_feed_path() -> Path:
    return Path.home() / "Downloads" / "TradeAlertChrome"


def poll_browser_feed(
    config: Config, store: StateStore, *,
    directory: Path | None = None, at: float | None = None,
    notification=None, alert_callback=None,
) -> dict:
    """Ingest a bounded, locally transferred batch. Never trust file attribution."""
    stats = {"files": 0, "alerts": 0, "notified": 0,
             "rejected": 0, "stale": 0, "duplicates": 0,
             "ocr_ok": 0, "ocr_unavailable": 0, "ocr_failed": 0}
    if not config.chrome_bridge_enabled:
        return stats
    folder = directory if directory is not None else browser_feed_path()
    if not folder.is_dir():
        return stats
    now = time.time() if at is None else float(at)
    notification = notification or notify
    for path in sorted(folder.glob("post-*.json"))[:MAX_FILES]:
        stats["files"] += 1
        try:
            name = POST_FILENAME.fullmatch(path.name)
            if (not name or path.is_symlink() or not path.is_file()
                    or not 1 <= path.stat().st_size <= MAX_FILE_BYTES):
                raise ValueError("Invalid Chrome bridge file")
            row = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(row, dict) or row.get("id") != name.group(1):
                raise ValueError("Post ID mismatches file")
            # Re-use central account-ID, username, visibility, ISO timestamp
            # and content checks. No untrusted links are accepted.
            parsed = parse_statuses(json.dumps([row]).encode("utf-8"),
                                    fetched_at=now)
            if len(parsed.posts) != 1:
                raise ValueError("Invalid Chrome post")
            post = parsed.posts[0]
            key = "TRUTH_PUBLIC:" + post.post_id
            if store.seen(key):
                stats["duplicates"] += 1
                continue
            age = now - post.published
            store.mark_seen(key, at=now)
            if age < -120 or age > config.chrome_bridge_max_age_seconds:
                stats["stale"] += 1
                continue
            image_text = ""
            if image_url_from_post(row):
                image_text, image_status = extract_image_text(row)
                if image_status == "OCR_OK":
                    stats["ocr_ok"] += 1
                elif image_status == "OCR_UNAVAILABLE":
                    stats["ocr_unavailable"] += 1
                elif image_status != "NO_IMAGE":
                    stats["ocr_failed"] += 1
                if image_status != "OCR_OK":
                    logging.warning(
                        "Chrome image post %s could not be assessed: %s",
                        post.post_id, image_status
                    )
            elif post.media_only:
                logging.info("Chrome post %s has media without approved image URL", post.post_id)
            if not post.text and not image_text:
                continue
            analysis_text = " ".join(part for part in (post.text, image_text) if part)
            signal = classify_trump_statement(analysis_text)
            score = signal.score
            if score < config.notification_min_score:
                continue
            caption = post.text[:450] if post.text else "[Ingen inläggstext]"
            image_evidence = ("\n[Bildtext via lokal OCR] " + image_text[:650]) if image_text else ""
            body = (f"Trump · {signal.priority} / {signal.category} · Chrome-källa\n"
                    f"{caption}{image_evidence}\n"
                    f"Publicerad {datetime.fromtimestamp(post.published).astimezone():%H:%M:%S}"
                    f" · mottagen +{int(max(0, age))} sek\n"
                    "Ingen automatisk handel.")
            stored = store.record_alert(
                item_key=key, source="TRUTH_CHROME",
                provider="Truth Social (local Chrome tab)",
                headline=analysis_text[:240], body=body, score=score,
                published=post.published, link=post.link, at=now,
            )
            if not stored:
                stats["duplicates"] += 1
                continue
            stats["alerts"] += 1
            if alert_callback:
                try:
                    alert_callback(store.unread_alert_count())
                except Exception:
                    logging.exception("Chrome bridge unread callback failed")
            if notification(f"Trade Alert · Trump {signal.priority} · {signal.category}", body):
                stats["notified"] += 1
            else:
                logging.error("Chrome bridge alert stored but Windows toast failed")
        except (OSError, UnicodeError, ValueError, json.JSONDecodeError,
                DirectUnavailable) as exc:
            stats["rejected"] += 1
            logging.warning("Rejected Chrome bridge message %s: %s",
                            path.name, type(exc).__name__)
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logging.exception("Failed to remove processed Chrome bridge file")
    return stats
