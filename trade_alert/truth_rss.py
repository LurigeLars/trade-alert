"""Bounded reader for the third-party, publicly offered Trump's Truth RSS feed.

The archive explicitly offers RSS subscriptions. This adapter does not access
Truth Social, scrape its pages or imply that the archive is a primary source.
"""
from __future__ import annotations

import asyncio
import hashlib
import html
import logging
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urlsplit

from .config import Config
from .trump_filter import classify_trump_statement
from .notifier import notify
from .state import StateStore

RSS_URL = "https://www.trumpstruth.org/feed"
MAX_FEED_BYTES = 524288
MAX_ITEMS = 80


class RSSUnavailable(RuntimeError):
    """RSS transport or source format did not satisfy the monitoring contract."""


class _PlainText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data):
        self.parts.append(data)


def _plain(value: str) -> str:
    p = _PlainText()
    p.feed(html.unescape(value))
    return " ".join("".join(p.parts).split())[:1500]


@dataclass(frozen=True)
class RSSPost:
    key: str
    text: str
    published: float
    link: str


@dataclass(frozen=True)
class RSSResult:
    posts: tuple[RSSPost, ...]
    etag: str | None
    modified: str | None
    not_modified: bool = False


def parse_rss(payload: bytes) -> tuple[RSSPost, ...]:
    """Parse bounded RSS 2.0 with stable GUID dedupe and publisher timestamps."""
    if len(payload) > MAX_FEED_BYTES or not payload:
        raise RSSUnavailable("empty or oversized RSS response")
    data = payload.lstrip()
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise RSSUnavailable("DTD/entity declarations are forbidden")
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise RSSUnavailable("invalid RSS XML") from exc
    if root.tag != "rss" or root.find("channel") is None:
        raise RSSUnavailable("expected RSS 2.0 channel")
    channel = root.find("channel")
    assert channel is not None
    posts = []
    seen = set()
    for node in channel.findall("item")[:MAX_ITEMS]:
        guid = (node.findtext("guid") or "").strip()
        url = (node.findtext("link") or "").strip()
        pub = (node.findtext("pubDate") or "").strip()
        if not guid:
            guid = url
        if not guid or not pub:
            continue
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname not in (
            "trumpstruth.org", "www.trumpstruth.org"
        ) or parsed.username or parsed.password:
            continue
        title = _plain(node.findtext("title") or "")
        description = _plain(node.findtext("description") or "")
        statement = description if len(description) > len(title) else title
        if not statement:
            continue
        try:
            timestamp = parsedate_to_datetime(pub)
            if timestamp.tzinfo is None or timestamp.utcoffset() is None:
                continue
            published = timestamp.astimezone(timezone.utc).timestamp()
        except (ValueError, TypeError, OverflowError, IndexError):
            continue
        key = hashlib.sha256(guid.encode("utf-8")).hexdigest()[:32]
        if key in seen:
            continue
        seen.add(key)
        posts.append(RSSPost(key=key, text=statement, link=url, published=published))
    if not posts and channel.findall("item"):
        raise RSSUnavailable("RSS entries lacked usable publication times or archive links")
    return tuple(posts)


class _RSSRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        parsed = urlsplit(newurl)
        if (parsed.scheme != "https" or parsed.hostname not in
            ("trumpstruth.org", "www.trumpstruth.org") or parsed.path != "/feed"):
            raise RSSUnavailable("RSS redirected outside approved feed")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_rss(*, etag: str | None = None, modified: str | None = None,
              timeout: float = 8.0) -> RSSResult:
    """HTTPS feed read, conditional GET, size cap, no arbitrary URL inputs."""
    headers = {"Accept": "application/rss+xml, application/xml, text/xml",
               "User-Agent": "TradeAlertRSS/1.0 (+personal-market-news-monitor)"}
    if etag:
        headers["If-None-Match"] = etag[:250]
    if modified:
        headers["If-Modified-Since"] = modified[:250]
    request = urllib.request.Request(RSS_URL, headers=headers)
    opener = urllib.request.build_opener(_RSSRedirect)
    try:
        with opener.open(request, timeout=timeout) as response:
            data = response.read(MAX_FEED_BYTES + 1)
            posts = parse_rss(data)
            return RSSResult(posts=posts,
                             etag=response.headers.get("ETag"),
                             modified=response.headers.get("Last-Modified"))
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return RSSResult(posts=(), etag=etag, modified=modified, not_modified=True)
        raise RSSUnavailable(f"RSS HTTP {exc.code}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RSSUnavailable(f"RSS transport {type(exc).__name__}") from exc


async def read_rss_once(config: Config, store: StateStore, *,
                        fetch: Callable = fetch_rss, now: float | None = None,
                        notification=None, alert_callback=None) -> dict:
    """Fetch in a worker thread; never block the event loop or News Flow.

    First successful fetch only establishes the baseline, preventing a flood
    of old archived posts when Trade Alert is updated or restarted.
    """
    if not config.truth_rss_enabled:
        return {"status": "DISABLED", "notified": 0, "new": 0}
    result = await asyncio.to_thread(
        fetch, etag=store.get_meta("truth_rss_etag"),
        modified=store.get_meta("truth_rss_modified")
    )
    moment = time.time() if now is None else now
    if result.etag:
        store.set_meta("truth_rss_etag", result.etag)
    if result.modified:
        store.set_meta("truth_rss_modified", result.modified)
    store.set_meta("truth_rss_last_success", datetime.fromtimestamp(
        moment, tz=timezone.utc).isoformat())
    if result.not_modified:
        return {"status": "NOT_MODIFIED", "notified": 0, "new": 0}
    initial = store.get_meta("truth_rss_initialized") is None
    # The direct primary reader owns fresh alerts when its latest check is healthy.
    # Keep fetching/baselining the archive to provide fallback after an outage.
    direct_healthy = False
    direct_at = store.get_meta("truth_direct_last_success")
    direct_error = store.get_meta("truth_direct_last_error")
    if config.truth_direct_enabled and direct_at and not direct_error:
        try:
            direct_time = datetime.fromisoformat(
                direct_at.replace("Z", "+00:00")).timestamp()
            direct_healthy = 0 <= moment - direct_time <= max(
                60, config.truth_direct_poll_seconds * 4)
        except ValueError:
            pass
    seen_count = notified = alerted = 0
    notification = notification or notify
    for post in sorted(result.posts, key=lambda p: p.published):
        key = "TRUMP_TRUTH_RSS:" + post.key
        if store.seen(key):
            continue
        seen_count += 1
        store.mark_seen(key, at=moment)
        age = moment - post.published
        if (initial or direct_healthy or age > config.truth_rss_max_age_seconds
                or age < -120):
            continue
        # Account identity comes from a third-party archive. Do not attribute
        # this as an authenticated primary Truth Social API event.
        signal = classify_trump_statement(post.text)
        score = signal.score
        if score < config.notification_min_score:
            continue
        body = (f"Trump · {signal.priority} / {signal.category} · oberoende RSS-arkiv (ej verifierad primärkälla)\n"
                + post.text[:600]
                + "\nPublicerad enligt RSS "
                + datetime.fromtimestamp(post.published).astimezone().strftime("%H:%M:%S")
                + f" · upptäckt +{int(max(0, age))} sek")
        inserted = store.record_alert(
            item_key=key, source="TRUMP_TRUTH_RSS",
            provider="Trump's Truth RSS (third party)",
            headline=post.text[:240], body=body, score=score,
            published=post.published, link=post.link, at=moment,
        )
        if not inserted:
            continue
        alerted += 1
        if alert_callback:
            try:
                alert_callback(store.unread_alert_count())
            except Exception:
                logging.exception("RSS unread count callback failed")
        if notification(f"Trade Alert · Trump {signal.priority} · {signal.category} (RSS)", body):
            notified += 1
        else:
            logging.error("RSS alert saved but Windows toast was not accepted")
    if initial:
        store.set_meta("truth_rss_initialized", datetime.fromtimestamp(
            moment, tz=timezone.utc).isoformat())
    return {"status": "BASELINED" if initial else "COMPLETE",
            "new": seen_count, "alerted": alerted, "notified": notified}
