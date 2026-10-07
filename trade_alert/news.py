from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable


CORE_TERMS = re.compile(
    r"\b(oil|crude|brent|wti|opec|opec\+|petroleum|barrel|refiner|refinery|gasoline|diesel)\b",
    re.IGNORECASE,
)
IMPACT_TERMS = re.compile(
    r"\b(iran|hormuz|saudi|russia|sanction|pipeline|tanker|inventory|inventories|eia|iea|"
    r"production|output|supply|ceasefire|israel|middle east|attack|strike|export|spr|"
    r"disruption|shutdown|outage|quota|cut|cuts|increase|deal)\b",
    re.IGNORECASE,
)
BRENT_SYMBOLS = {"ICEEUR:BRN1!", "TVC:UKOIL"}


@dataclass(frozen=True, slots=True)
class Headline:
    source: str
    item_id: str
    title: str
    published: float | None
    provider: str | None = None
    link: str | None = None
    urgency: int | None = None
    related_symbols: tuple[str, ...] = ()

    @property
    def key(self) -> str:
        return f"{self.source}:{self.item_id}"

    @property
    def age_seconds(self) -> float | None:
        if self.published is None:
            return None
        return max(0.0, time.time() - self.published)

    def published_label(self) -> str:
        if self.published is None:
            return "tid okänd"
        dt = datetime.fromtimestamp(self.published, tz=timezone.utc).astimezone()
        return dt.strftime("%H:%M:%S")


def _provider_name(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("name", "id", "provider"):
            if isinstance(value.get(key), str) and value[key].strip():
                return value[key].strip()
    return None


def _published(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        value = float(value)
        if value > 10_000_000_000:
            value /= 1000.0
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def _related_symbols(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list):
        return ()
    symbols: list[str] = []
    for item in value:
        if isinstance(item, str):
            symbols.append(item)
        elif isinstance(item, dict):
            symbol = item.get("symbol") or item.get("full_name")
            if isinstance(symbol, str):
                symbols.append(symbol)
    return tuple(dict.fromkeys(symbols))


def _walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return
        yield from _walk(decoded)
        return
    if isinstance(value, list):
        for item in value:
            yield from _walk(item)
        return
    if not isinstance(value, dict):
        return

    title = value.get("title") or value.get("headline")
    if isinstance(title, str) and title.strip():
        yield value
    for child in value.values():
        if isinstance(child, (dict, list, str)):
            yield from _walk(child)


def normalize_headlines(payload: Any, *, source: str) -> list[Headline]:
    items: list[Headline] = []
    seen: set[str] = set()
    for row in _walk(payload):
        title = str(row.get("title") or row.get("headline") or "").strip()
        if not title:
            continue
        published = _published(
            row.get("published")
            or row.get("published_at")
            or row.get("publishedAt")
            or row.get("timestamp")
            or row.get("time")
        )
        raw_id = row.get("id") or row.get("story_id") or row.get("storyId") or row.get("url") or row.get("link")
        if raw_id is None:
            raw_id = hashlib.sha256(f"{title}|{published}".encode("utf-8")).hexdigest()[:24]
        item_id = str(raw_id)
        if item_id in seen:
            continue
        seen.add(item_id)
        link = row.get("link") or row.get("url") or row.get("storyPath")
        urgency = row.get("urgency")
        try:
            urgency = int(urgency) if urgency is not None else None
        except (TypeError, ValueError):
            urgency = None
        items.append(
            Headline(
                source=source,
                item_id=item_id,
                title=title,
                published=published,
                provider=_provider_name(row.get("provider")),
                link=str(link) if isinstance(link, str) else None,
                urgency=urgency,
                related_symbols=_related_symbols(row.get("relatedSymbols") or row.get("related_symbols")),
            )
        )
    items.sort(key=lambda item: item.published or 0, reverse=True)
    return items


def relevance_score(item: Headline) -> int:
    score = 0
    if CORE_TERMS.search(item.title):
        score += 2
    if IMPACT_TERMS.search(item.title):
        score += 2
    if item.urgency == 1:
        score += 2
    if BRENT_SYMBOLS.intersection(item.related_symbols):
        score += 2
    return score


async def fetch_dtv_news(*, url: str, watchlist_id: str, since: str | None, limit: int) -> list[Headline]:
    from .mcp_client import call_json_tool
    args: dict[str, Any] = {"watchlist_id": watchlist_id, "limit": limit}
    if since:
        args["since"] = since
    payload = await call_json_tool(url, "news_flow_get", args)
    return normalize_headlines(payload, source="DTV")


async def fetch_official_news(*, url: str, symbol: str, limit: int) -> list[Headline]:
    from .mcp_client import call_json_tool
    payload = await call_json_tool(
        url,
        "intelligence_state",
        {"view": "TRADINGVIEW_NEWS", "symbol": symbol, "limit": limit, "offset": 0},
    )
    return normalize_headlines(payload, source=f"TV:{symbol}")
