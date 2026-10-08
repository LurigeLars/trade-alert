"""Low-latency local intake for *authorized* breaking-news relays.

Does not fetch, scrape, authenticate to, or bypass controls on any upstream
website. A provider adapter with permitted access writes atomic JSON files into
a local-only inbox. This module does not decide whether that adapter is licensed.
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from .config import Config, app_dir
from .notifier import notify
from .state import StateStore

SOURCE_ID = re.compile(r"^[A-Z][A-Z0-9_:-]{2,79}$")
ITEM_ID = re.compile(r"^[A-Za-z0-9_:-]{1,128}$")
MAX_FILE_BYTES = 16384
MAX_BATCH_FILES = 40


def inbox_path() -> Path:
    return app_dir() / "breaking-inbox"


def _utc_timestamp(raw: object) -> float:
    if not isinstance(raw, str):
        raise ValueError("published_at must contain an offset")
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid published_at") from exc
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError("published_at must contain an offset")
    return dt.astimezone(timezone.utc).timestamp()


def parse_breaking_record(
    payload: object,
    *,
    approved_sources: tuple[str, ...],
    now: float,
    max_age_seconds: int,
) -> dict:
    """Admit only explicit local source IDs; never trust attribution implicitly."""
    if not isinstance(payload, dict):
        raise ValueError("breaking record must be a JSON object")
    source_id = payload.get("source_id")
    item_id = payload.get("event_id")
    title = payload.get("headline")
    link = payload.get("url")
    if not isinstance(source_id, str) or not SOURCE_ID.fullmatch(source_id):
        raise ValueError("invalid source_id")
    if source_id not in approved_sources:
        raise ValueError("source is not configured as approved for this relay")
    if not isinstance(item_id, str) or not ITEM_ID.fullmatch(item_id):
        raise ValueError("invalid event_id")
    if not isinstance(title, str) or not (1 <= len(title.strip()) <= 1000):
        raise ValueError("invalid headline")
    if not isinstance(link, str):
        raise ValueError("missing source URL")
    try:
        url = urlsplit(link)
    except ValueError as exc:
        raise ValueError("invalid URL") from exc
    if (url.scheme != "https" or not url.hostname or url.username or url.password or
            url.fragment):
        raise ValueError("URL must be secure and unambiguous")
    if source_id == "TRUTHSOCIAL_REALDONALDTRUMP":
        if (url.hostname not in ("truthsocial.com", "www.truthsocial.com") or
                url.path != f"/@realDonaldTrump/posts/{item_id}" or url.query):
            raise ValueError("Truth Social primary URL must match canonical account and post ID")
    pub = _utc_timestamp(payload.get("published_at"))
    if pub > now + 120:
        raise ValueError("publication timestamp is in the future")
    age = now - pub
    if age > max_age_seconds:
        return {"stale": True, "source_id": source_id, "event_id": item_id}
    if payload.get("acquisition") not in ("LICENSED", "AUTHORIZED_RELAY"):
        raise ValueError("only licensed/authorized relay payloads enter this automatic path")
    return {
        "stale": False,
        "key": f"BREAKING:{source_id}:{item_id}",
        "source_id": source_id,
        "event_id": item_id,
        "title": title.strip(),
        "link": link,
        "published": pub,
        "age_seconds": max(0, int(age)),
    }


def poll_breaking_inbox(
    config: Config,
    store: StateStore,
    *,
    directory: Path | None = None,
    at: float | None = None,
    notification=None,
    alert_callback=None,
) -> dict:
    """Consume bounded atomic inbox files without waiting for network MCP calls.

    A file is always removed from the inbound folder after success/rejection.
    We never claim toast delivery if the OS notification API fails.
    """
    directory = directory or inbox_path()
    if not config.breaking_inbox_enabled:
        return {"accepted": 0, "notified": 0, "rejected": 0, "stale": 0}
    directory.mkdir(parents=True, exist_ok=True)
    moment = time.time() if at is None else float(at)
    notification = notification or notify
    stats = {"accepted": 0, "notified": 0, "rejected": 0, "stale": 0}
    for path in sorted(directory.glob("*.json"))[:MAX_BATCH_FILES]:
        try:
            if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError("invalid or oversized inbox file")
            parsed = parse_breaking_record(
                json.loads(path.read_text(encoding="utf-8")),
                approved_sources=config.breaking_authorized_sources,
                now=moment,
                max_age_seconds=config.breaking_max_age_seconds,
            )
            if parsed["stale"]:
                stats["stale"] += 1
                continue
            key = parsed["key"]
            if store.seen(key):
                continue
            body = (f"{parsed['title']}\n"
                    f"Primärkälla/relay: {parsed['source_id']} · "
                    f"publicerad {datetime.fromtimestamp(parsed['published']).astimezone():%H:%M:%S}"
                    f" · upptäckt +{parsed['age_seconds']} s\n"
                    "Uttalandet är inte oberoende verifierat. Ingen automatisk handel.")
            created = store.record_alert(
                item_key=key,
                source="BREAKING_POLICY",
                provider=parsed["source_id"],
                headline=parsed["title"],
                body=body,
                score=10,
                published=parsed["published"],
                link=parsed["link"],
                at=moment,
            )
            store.mark_seen(key, at=moment)
            if created:
                stats["accepted"] += 1
                if alert_callback:
                    try:
                        alert_callback(store.unread_alert_count())
                    except Exception:
                        logging.exception("breaking alert callback failed")
                if notification("Trade Alert · POLICY", body):
                    stats["notified"] += 1
                else:
                    logging.error("Breaking alert saved unread but Windows toast failed: %s", key)
        except (ValueError, json.JSONDecodeError, UnicodeError, OSError) as exc:
            stats["rejected"] += 1
            logging.warning("Rejected local breaking event %s: %s", path.name, exc)
        finally:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                logging.exception("Could not remove handled breaking event %s", path)
    return stats
