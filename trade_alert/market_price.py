"""Market shock detector from verified DTV resident completed 1-minute bars.

Read-only MCP client, never mutates visible TradingView chart/panes.
The caller must supply DTV worker-owned, resident 1m subscriptions.
"""
from __future__ import annotations

import math
import time
from typing import Any
from datetime import datetime, timezone

from .config import Config
from .market_correlation import MarketCorrelationError, parse_market_shock
from .mcp_client import MCPToolError, call_json_tool

SOURCE_ID = "DTV_RESIDENT"


def _object(value: Any) -> dict:
    if not isinstance(value, dict):
        raise MarketCorrelationError("non-object DTV payload")
    if isinstance(value.get("result"), dict) and "snapshots" in value["result"]:
        return value["result"]
    return value


def _verified_bars(snap: dict, expected_symbol: str, *, now: float) -> dict[int, float]:
    if not isinstance(snap, dict) or snap.get("success") is not True:
        raise MarketCorrelationError("DTV resident pane unavailable")
    if snap.get("resolved_symbol") != expected_symbol or str(snap.get("resolution")) != "1":
        raise MarketCorrelationError("DTV resident underlying or 1m timeframe mismatch")
    md = snap.get("metadata") or {}
    quote = snap.get("quote") or {}
    if md.get("instrument_type") != "futures":
        raise MarketCorrelationError("not a verified exchange futures instrument")
    if md.get("bar_time_is_period_start") is not True:
        raise MarketCorrelationError("bar timing convention not verified")
    if md.get("realtime_status") != "realtime" or quote.get("is_delay") is not False:
        raise MarketCorrelationError("DTV futures feed delayed or entitlement unknown")
    delay_minutes = md.get("delay_minutes")
    if delay_minutes not in (None, 0):
        raise MarketCorrelationError("market data delayed")
    age = quote.get("age_at_retrieval_ms")
    if not isinstance(age, (float, int)) or not math.isfinite(age) or age < 0 or age > 120000:
        raise MarketCorrelationError("DTV resident quote timestamp stale/unavailable")
    bars = snap.get("recent_bars")
    current = snap.get("current_bar")
    if not isinstance(bars, list) or not isinstance(current, dict) or len(bars) < 3:
        raise MarketCorrelationError("insufficient completed 1m bars")
    active_t = current.get("time")
    if not isinstance(active_t, (float, int)) or active_t <= 0 or int(active_t) % 60:
        raise MarketCorrelationError("invalid current 1m start")
    if now - active_t < -5 or now - active_t > 125:
        raise MarketCorrelationError("current bar not fresh")
    # The bar tagged active_t is still open. NEVER ingest its close.
    complete: dict[int, float] = {}
    for bar in bars:
        if not isinstance(bar, dict):
            continue
        t, c = bar.get("time"), bar.get("close")
        if (isinstance(t, (int, float)) and isinstance(c, (int, float))
                and not isinstance(c, bool) and math.isfinite(c) and c > 0
                and int(t) == t and t < active_t and int(t) % 60 == 0):
            complete[int(t)] = float(c)
    return complete


def parse_resident_snapshot(payload: object, config: Config, *, now: float | None = None) -> list[dict]:
    """Emit source-stamped, fully completed shocks; fail closed on any leg.

    Each event is constructed from two consecutive closed candles per
    underlying (previous minute's close and current completed close).
    """
    moment = time.time() if now is None else float(now)
    data = _object(payload)
    if data.get("success") is not True or data.get("missing") or data.get("failed_count"):
        raise MarketCorrelationError("DTV realtime_snapshot incomplete")
    snapshots = data.get("snapshots")
    if not isinstance(snapshots, list):
        raise MarketCorrelationError("no DTV resident snapshots")
    by_symbol: dict[str, dict] = {}
    for row in snapshots:
        symbol = row.get("resolved_symbol") if isinstance(row, dict) else None
        if symbol in (config.market_correlation_brent_symbol, config.market_correlation_nasdaq_symbol):
            if symbol in by_symbol:
                raise MarketCorrelationError("ambiguous duplicate resident futures")
            by_symbol[symbol] = row
    if len(by_symbol) != 2:
        raise MarketCorrelationError("one or both exact futures references unavailable")
    brent = _verified_bars(by_symbol[config.market_correlation_brent_symbol],
                           config.market_correlation_brent_symbol, now=moment)
    nasdaq = _verified_bars(by_symbol[config.market_correlation_nasdaq_symbol],
                            config.market_correlation_nasdaq_symbol, now=moment)
    event_bars = sorted(set(brent) & set(nasdaq))
    results = []
    for bar_start in event_bars:
        prev_start = bar_start - 60
        if prev_start not in brent or prev_start not in nasdaq:
            continue
        bar_end = bar_start + 60
        if not (0 <= moment - bar_end <= config.market_correlation_max_age_seconds):
            continue
        body = {
            "event_id": f"{bar_end}-BZ-NQ",
            "provider": SOURCE_ID,
            "bar_seconds": 60,
            "realtime": True,
            "delayed": False,
            "brent": {
                "symbol": config.market_correlation_brent_symbol,
                "bar_end": datetime.fromtimestamp(bar_end, timezone.utc).isoformat().replace("+00:00", "Z"),
                "previous_close": brent[prev_start],
                "close": brent[bar_start],
            },
            "nasdaq": {
                "symbol": config.market_correlation_nasdaq_symbol,
                "bar_end": __import__("datetime").datetime.fromtimestamp(
                    bar_end, __import__("datetime").timezone.utc
                ).isoformat().replace("+00:00", "Z"),
                "previous_close": nasdaq[prev_start],
                "close": nasdaq[bar_start],
            },
        }
        try:
            parse_market_shock(body, config, now=moment)
        except MarketCorrelationError as exc:
            if "fixed research signal" in str(exc):
                continue
            raise
        results.append(body)
    return results


async def collect_resident_events(config: Config) -> list[dict]:
    if not config.market_correlation_enabled:
        return []
    if SOURCE_ID not in config.market_correlation_authorized_sources:
        raise MarketCorrelationError("DTV source not locally authorized")
    try:
        data = await call_json_tool(
            config.dtv_url,
            "realtime_snapshot",
            {"handles": ["cross-brent-dec26-1m", "cross-nasdaq-1m"],
             "mode": "decision", "bars": 8, "include_studies": False,
             "stale_after_ms": 120000},
        )
    except MCPToolError as exc:
        raise MarketCorrelationError("DTV realtime snapshot unavailable") from exc
    return parse_resident_snapshot(data, config)
