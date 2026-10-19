"""Fail-closed, optional Brent/Nasdaq minute-shock to news-timestamp correlation.

Price observations are delivered by an already-authorized local producer.
This module does not fetch market data, infer underlying instruments, make
trading decisions, or assert that a news headline caused a price movement.
"""
from __future__ import annotations

import json
import logging
import math
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from .config import Config, app_dir
from .news import Headline, normalize_news_link, relevance_score
from .notifier import alert_click, notify
from .state import StateStore

MAX_EVENT_BYTES = 8192
MAX_EVENTS_PER_CYCLE = 20
SOURCE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,79}$")
EVENT_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
PRIMARY_PROVIDERS = frozenset({
    "reuters", "dow jones newswires", "bloomberg", "associated press",
    "trading economics",
})
MAX_NEWS_LOOKBACK_SECONDS = 1800
MIN_SEPARATION_SECONDS = 1800


class MarketCorrelationError(ValueError):
    """Event lacks the source, timing or underlying proof needed to act."""


@dataclass(frozen=True, slots=True)
class MarketShock:
    event_id: str
    provider: str
    bar_end: float
    brent_symbol: str
    nasdaq_symbol: str
    brent_change_pct: float
    nasdaq_change_pct: float

    @property
    def key(self) -> str:
        return f"CROSS_MARKET:{self.provider}:{self.event_id}"


@dataclass(frozen=True, slots=True)
class CatalystMatch:
    label: str
    headline: Headline | None
    lag_seconds: int | None


def _utc_timestamp(value: object) -> float:
    if not isinstance(value, str):
        raise MarketCorrelationError("bar_end must be an ISO-8601 UTC timestamp")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise MarketCorrelationError("invalid bar_end timestamp") from exc
    if dt.tzinfo is None or dt.utcoffset().total_seconds() != 0:
        raise MarketCorrelationError("bar_end must explicitly use UTC")
    return dt.timestamp()


def _price(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise MarketCorrelationError("price must be a finite positive number")
    price = float(value)
    if not math.isfinite(price) or price <= 0:
        raise MarketCorrelationError("price must be a finite positive number")
    return price


def parse_market_shock(payload: object, config: Config, *, now: float) -> MarketShock:
    if not isinstance(payload, dict):
        raise MarketCorrelationError("event must be an object")
    source = payload.get("provider")
    event_id = payload.get("event_id")
    if not isinstance(source, str) or not SOURCE_RE.fullmatch(source):
        raise MarketCorrelationError("invalid source identifier")
    if source not in config.market_correlation_authorized_sources:
        raise MarketCorrelationError("market-data producer not allowlisted")
    if not isinstance(event_id, str) or not EVENT_ID_RE.fullmatch(event_id):
        raise MarketCorrelationError("invalid event ID")
    if payload.get("bar_seconds") != 60 or payload.get("realtime") is not True:
        raise MarketCorrelationError("only confirmed real-time one-minute bars are accepted")
    if payload.get("delayed") is not False:
        raise MarketCorrelationError("delayed/unknown entitlement cannot produce a live alert")

    brent = payload.get("brent")
    nasdaq = payload.get("nasdaq")
    if not isinstance(brent, dict) or not isinstance(nasdaq, dict):
        raise MarketCorrelationError("both price legs must be present")
    if brent.get("symbol") != config.market_correlation_brent_symbol:
        raise MarketCorrelationError("Brent contract differs from the configured reference")
    if nasdaq.get("symbol") != config.market_correlation_nasdaq_symbol:
        raise MarketCorrelationError("Nasdaq contract differs from the configured reference")
    t_brent = _utc_timestamp(brent.get("bar_end"))
    t_nasdaq = _utc_timestamp(nasdaq.get("bar_end"))
    if t_brent != t_nasdaq or t_brent % 60 != 0:
        raise MarketCorrelationError("bar-end timestamps must match at a minute boundary")
    age = now - t_brent
    if age < -15 or age > config.market_correlation_max_age_seconds:
        raise MarketCorrelationError("price event is stale or from the future")

    bprev = _price(brent.get("previous_close"))
    bnow = _price(brent.get("close"))
    nprev = _price(nasdaq.get("previous_close"))
    nnow = _price(nasdaq.get("close"))
    bmove = 100.0 * (bnow / bprev - 1.0)
    nmove = 100.0 * (nnow / nprev - 1.0)
    if bmove > -0.5 or nmove < 0.15:
        raise MarketCorrelationError("price event does not satisfy the fixed research signal")
    return MarketShock(
        event_id=event_id,
        provider=source,
        bar_end=t_brent,
        brent_symbol=brent["symbol"],
        nasdaq_symbol=nasdaq["symbol"],
        brent_change_pct=bmove,
        nasdaq_change_pct=nmove,
    )


def match_catalyst(shock: MarketShock, headlines: Iterable[Headline]) -> CatalystMatch:
    """Select the earliest *eligible published headline seen*, never infer causality.

    Eligible means reputable named wire, topical headline, validated URL,
    and a published timestamp in the 30 minutes preceding the shock.
    Later reports and undated stories cannot be the event's causal trigger.
    """
    eligible = []
    for news in headlines:
        provider = (news.provider or "").strip().casefold()
        published = news.published
        if (provider not in PRIMARY_PROVIDERS or published is None
                or not math.isfinite(published) or not news.link
                or not normalize_news_link(news.link)
                or relevance_score(news) < 3):
            continue
        lag = shock.bar_end - published
        if 0 <= lag <= MAX_NEWS_LOOKBACK_SECONDS:
            eligible.append((published, news))
    if not eligible:
        return CatalystMatch("NO_VERIFIED_PRE_EVENT_HEADLINE", None, None)
    # Earliest eligible first-seen publication among the bounded available feed.
    published, headline = min(eligible, key=lambda candidate: candidate[0])
    return CatalystMatch(
        "TIMESTAMP_MATCH_ONLY",
        headline,
        int(round(shock.bar_end - published)),
    )


def incident_inbox_path() -> Path:
    return app_dir() / "cross-market-inbox"


def process_market_incidents(
    config: Config,
    store: StateStore,
    headlines: Iterable[Headline],
    *,
    directory: Path | None = None,
    records: Iterable[dict] | None = None,
    now: float | None = None,
    notification=None,
    alert_callback=None,
) -> dict[str, int]:
    """Consume bounded atomic .json events using existing Trade Alert alerts/dedupe.

    The optional producer must be wired separately. A failed event never
    becomes a notification. No claim of live monitoring when disabled.
    """
    result = {"accepted": 0, "notified": 0, "rejected": 0, "suppressed": 0}
    if not config.market_correlation_enabled:
        return result
    if not config.market_correlation_authorized_sources:
        logging.error("Cross-market correlation enabled without an authorized price producer")
        result["rejected"] += 1
        return result
    moment = time.time() if now is None else float(now)
    news = tuple(headlines)
    if records is None:
        folder = directory or incident_inbox_path()
        folder.mkdir(parents=True, exist_ok=True)
        candidates = [(p, None) for p in sorted(folder.glob("*.json"))[:MAX_EVENTS_PER_CYCLE]]
    else:
        # Internal, validated DTV snapshots are passed directly (no filesystem ingress).
        candidates = [(None, record) for record in list(records)[:MAX_EVENTS_PER_CYCLE]]
    for path, payload in candidates:
        try:
            if path is not None:
                if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_EVENT_BYTES:
                    raise MarketCorrelationError("invalid/oversized event file")
                payload = json.loads(path.read_text(encoding="utf-8"))
            event = parse_market_shock(payload, config, now=moment)
            if store.seen(event.key):
                result["suppressed"] += 1
                continue
            last = store.get_meta("cross_market_last_event_at")
            if last is not None:
                try:
                    if 0 <= event.bar_end - float(last) < MIN_SEPARATION_SECONDS:
                        store.mark_seen(event.key, at=moment)
                        result["suppressed"] += 1
                        continue
                except ValueError:
                    logging.warning("Ignoring invalid previous cross-market event cursor")
            evidence = match_catalyst(event, news)
            timestamp = datetime.fromtimestamp(event.bar_end, timezone.utc).astimezone()
            title = (
                f"Brent {event.brent_change_pct:+.2f}% / "
                f"Nasdaq {event.nasdaq_change_pct:+.2f}% (1m)"
            )
            body = f"{title} · {timestamp:%H:%M:%S}\n"
            link = None
            if evidence.headline is not None:
                body += (
                    f"Tidsmatchad: {evidence.headline.provider}, "
                    f"{evidence.lag_seconds}s tidigare: {evidence.headline.title}\n"
                    "Publiceringstiden är verifierbar; orsakssambandet är inte bevisat."
                )
                link = normalize_news_link(evidence.headline.link)
            else:
                body += (
                    "Ingen föregående primärnyhet tidsverifierad i tillgängligt flöde. "
                    "Orsak OKÄND; källorna kan vara ofullständiga."
                )
            saved = store.record_alert(
                item_key=event.key,
                source="CROSS_MARKET_SHOCK",
                provider=event.provider,
                headline=title,
                body=body,
                published=event.bar_end,
                score=8,
                link=link,
                at=moment,
            )
            store.mark_seen(event.key, at=moment)
            if not saved:
                result["suppressed"] += 1
                continue
            from .market_evidence import record_incident
            record_incident(store, event, evidence, now=moment)
            store.set_meta("cross_market_last_event_at", str(event.bar_end))
            result["accepted"] += 1
            if alert_callback:
                try:
                    alert_callback(store.unread_alert_count())
                except Exception:
                    logging.exception("cross-market UI callback failed")
            sender = notification or (lambda t, b, key=event.key: notify(
                t, b, item_key=key,
                on_click=alert_click(store.path, key, alert_callback),
            ))
            if sender("Trade Alert · MARKET SHOCK", body):
                result["notified"] += 1
            else:
                logging.warning("Cross-market shock saved; toast delivery failed")
        except (MarketCorrelationError, ValueError, OSError, UnicodeError, TypeError) as exc:
            result["rejected"] += 1
            logging.warning("Rejected cross-market event %s: %s", path.name if path else "resident", exc)
        finally:
            if path is not None:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    logging.exception("Cannot remove consumed cross-market file %s", path)
    return result
