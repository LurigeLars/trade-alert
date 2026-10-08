from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from .mcp_client import MCPToolError, call_json_tool


CORE_TERM_LABELS = (
    "oil", "crude", "brent", "wti", "opec", "petroleum", "barrel",
    "refiner", "refinery", "gasoline", "diesel", "fuel",
)
STANDALONE_HIGH_IMPACT_TERM_LABELS = ("hormuz",)
IMPACT_TERM_LABELS = (
    "iran", "hormuz", "saudi", "russia", "sanction", "pipeline", "tanker",
    "inventory", "inventories", "eia", "iea", "production", "output", "supply",
    "ceasefire", "israel", "middle east", "attack", "strike", "export", "spr",
    "disruption", "shutdown", "outage", "quota", "cut", "cuts", "increase", "deal",
)

CORE_TERMS = re.compile(
    r"\b(?:" + "|".join(re.escape(term) for term in CORE_TERM_LABELS) + r")\b",
    re.IGNORECASE,
)
IMPACT_TERMS = re.compile(
    r"\b(?:" + "|".join(re.escape(term) for term in IMPACT_TERM_LABELS) + r")\b",
    re.IGNORECASE,
)
# US policy statements about military operations in Iran can immediately reprice
# oil even if the provider headline has no oil symbol/word.
IRAN_POLICY_ACTOR = re.compile(r"\b(?:trump|president|white house|united states|u\.?s\.?)\b", re.IGNORECASE)
IRAN_POLICY_COUNTRY = re.compile(r"\b(?:iran|tehran|hormuz)\b", re.IGNORECASE)
IRAN_POLICY_ACTION = re.compile(
    r"\b(?:attack|attacks|attacking|strike|strikes|striking|military|"
    r"talks|negotiations|sanction|sanctions|war|ceasefire|blockade)\b",
    re.IGNORECASE,
)

STANDALONE_HIGH_IMPACT_TERMS = re.compile(
    r"\b(?:" + "|".join(re.escape(term) for term in STANDALONE_HIGH_IMPACT_TERM_LABELS) + r")\b",
    re.IGNORECASE,
)

# Related symbols are routing evidence only. They must not, by themselves, create an alert.
OIL_ROUTING_SYMBOLS = {
    "ICEEUR:BRN1!",
    "TVC:UKOIL",
    "NYMEX:CL1!",
    "TVC:USOIL",
    "NYMEX:RB1!",
    "NYMEX:HO1!",
}
OIL_WATCHLIST_ANCHORS = OIL_ROUTING_SYMBOLS


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


@dataclass(frozen=True, slots=True)
class DTVWatchlistContext:
    watchlist_id: str
    name: str | None
    symbols: tuple[str, ...]
    auto_discovered: bool


@dataclass(frozen=True, slots=True)
class DTVNewsBatch:
    headlines: tuple[Headline, ...]
    context: DTVWatchlistContext
    coverage_complete: bool


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


def _root_dict(payload: Any) -> dict[str, Any]:
    if isinstance(payload, dict) and isinstance(payload.get("result"), dict):
        return payload["result"]
    if isinstance(payload, dict):
        return payload
    raise MCPToolError("provider payload is not an object")


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
        link = row.get("link") or row.get("url") or row.get("storyPath") or row.get("story_path")
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
                provider=_provider_name(row.get("provider") or row.get("publisher")),
                link=str(link) if isinstance(link, str) else None,
                urgency=urgency,
                related_symbols=_related_symbols(
                    row.get("relatedSymbols")
                    or row.get("related_symbols")
                    or row.get("related_tickers")
                ),
            )
        )
    items.sort(key=lambda item: item.published or 0, reverse=True)
    return items


def relevance_score(item: Headline) -> int:
    """Deterministic oil relevance for a broad market news feed.

    Impact words and urgency only count when the headline has explicit oil context or the provider
    supplied an oil-routing symbol. A related symbol alone is deliberately insufficient.
    """
    core = bool(CORE_TERMS.search(item.title))
    impact = bool(IMPACT_TERMS.search(item.title))
    standalone_high_impact = bool(STANDALONE_HIGH_IMPACT_TERMS.search(item.title))
    routed = bool(OIL_ROUTING_SYMBOLS.intersection(item.related_symbols))

    score = 0
    # Standalone policy surprise: do not require an oil keyword.
    if (IRAN_POLICY_ACTOR.search(item.title)
            and IRAN_POLICY_COUNTRY.search(item.title)
            and IRAN_POLICY_ACTION.search(item.title)):
        score += 4
    if core:
        score += 2
    if standalone_high_impact:
        score += 4
    elif impact and (core or routed):
        score += 2
    if routed:
        score += 1
    if item.urgency == 1 and (core or routed):
        score += 1
    return score


async def resolve_dtv_watchlist(*, url: str, configured_id: str | None = None) -> DTVWatchlistContext:
    if configured_id:
        return DTVWatchlistContext(
            watchlist_id=str(configured_id),
            name=None,
            symbols=(),
            auto_discovered=False,
        )

    payload = _root_dict(await call_json_tool(url, "watchlist_get", {}))
    if payload.get("success", True) is not True:
        raise MCPToolError("watchlist_get: source returned success=false")

    raw_id = payload.get("list_id")
    watchlist_id = str(raw_id) if raw_id is not None else ""
    if not watchlist_id.isdigit() or int(watchlist_id) <= 0:
        raise MCPToolError("watchlist_get: active watchlist has no numeric list_id")

    symbols: list[str] = []
    for row in payload.get("symbols") or []:
        if isinstance(row, dict) and isinstance(row.get("symbol"), str):
            symbols.append(row["symbol"])
        elif isinstance(row, str):
            symbols.append(row)

    anchors = OIL_WATCHLIST_ANCHORS.intersection(symbols)
    if not anchors:
        raise MCPToolError(
            "watchlist_get: active watchlist lacks a verified oil anchor "
            f"({', '.join(sorted(OIL_WATCHLIST_ANCHORS))})"
        )

    name = payload.get("list_name")
    return DTVWatchlistContext(
        watchlist_id=watchlist_id,
        name=str(name) if isinstance(name, str) and name.strip() else None,
        symbols=tuple(dict.fromkeys(symbols)),
        auto_discovered=True,
    )


async def fetch_dtv_news(
    *,
    url: str,
    context: DTVWatchlistContext,
    since: str | None,
    limit: int,
) -> DTVNewsBatch:
    args: dict[str, Any] = {"watchlist_id": context.watchlist_id, "limit": limit}
    if since:
        args["since"] = since
    payload = await call_json_tool(url, "news_flow_get", args)
    root = _root_dict(payload)

    coverage_complete = not bool(root.get("source_window_truncated", False))
    if since is not None and root.get("freshness_boundary_reached") is False:
        coverage_complete = False

    return DTVNewsBatch(
        headlines=tuple(normalize_headlines(payload, source="DTV_NEWS_FLOW")),
        context=context,
        coverage_complete=coverage_complete,
    )


async def fetch_official_news(*, url: str, symbol: str, limit: int) -> list[Headline]:
    payload = await call_json_tool(
        url,
        "intelligence_state",
        {"view": "TRADINGVIEW_NEWS", "symbol": symbol, "limit": limit, "offset": 0},
    )
    return normalize_headlines(payload, source=f"TV:{symbol}")
