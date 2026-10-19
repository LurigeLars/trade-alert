"""Bounded local audit of first-seen news and shock-to-headline revisions.

Operational event evidence only, no portfolio/trade decisions or order routing.
Stores explicit publication and *our* first observation separately.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Iterable

from .market_correlation import (
    MAX_NEWS_LOOKBACK_SECONDS,
    MarketShock,
    CatalystMatch,
    match_catalyst,
)
from .news import Headline, normalize_news_link
from .state import StateStore

CACHE_RETENTION_SECONDS = 3 * 3600
INCIDENT_RETENTION_SECONDS = 30 * 24 * 3600
RECHECK_WINDOW_SECONDS = 90 * 60


def ensure_tables(store: StateStore) -> None:
    store.con.executescript(
        """
        CREATE TABLE IF NOT EXISTS cross_market_news (
            dedupe_key TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            provider TEXT NOT NULL,
            title TEXT NOT NULL,
            published REAL NOT NULL,
            first_seen REAL NOT NULL,
            link TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_cross_market_news_pub
            ON cross_market_news(published);
        CREATE TABLE IF NOT EXISTS cross_market_incidents (
            event_key TEXT PRIMARY KEY,
            shock_end REAL NOT NULL,
            detected_at REAL NOT NULL,
            provider TEXT NOT NULL,
            event_id TEXT NOT NULL,
            brent_ref TEXT NOT NULL,
            nq_ref TEXT NOT NULL,
            brent_move REAL NOT NULL,
            nq_move REAL NOT NULL,
            evidence_label TEXT NOT NULL,
            linked_news_key TEXT,
            link_published REAL,
            link_first_seen REAL,
            updated_at REAL NOT NULL,
            upgrade_alerted INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_cross_market_incidents_end
            ON cross_market_incidents(shock_end);
        CREATE TABLE IF NOT EXISTS cross_market_revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_key TEXT NOT NULL,
            changed_at REAL NOT NULL,
            previous_label TEXT,
            evidence_label TEXT NOT NULL,
            linked_news_key TEXT,
            link_published REAL,
            link_first_seen REAL
        );
        """
    )


def cache_headlines(store: StateStore, headlines: Iterable[Headline], *, now: float | None = None) -> int:
    moment = time.time() if now is None else float(now)
    ensure_tables(store)
    added = 0
    for headline in headlines:
        link = normalize_news_link(headline.link)
        pub = headline.published
        if not (link and pub is not None and isinstance(pub, (int, float))
                and math.isfinite(pub) and moment - CACHE_RETENTION_SECONDS <= pub <= moment + 30):
            continue
        provider = (headline.provider or "").strip()
        if not provider:
            continue
        first_seen = store.source_first_seen(headline.dedupe_key, headline.source)
        if first_seen is None:
            first_seen = moment
        row = store.con.execute(
            """INSERT OR IGNORE INTO cross_market_news
               (dedupe_key, source, provider, title, published, first_seen, link)
               VALUES(?, ?, ?, ?, ?, ?, ?)""",
            (headline.dedupe_key, headline.source, provider, headline.title[:600],
             float(pub), first_seen, link),
        )
        added += int(row.rowcount > 0)
    store.con.execute(
        "DELETE FROM cross_market_news WHERE first_seen < ?",
        (moment - CACHE_RETENTION_SECONDS,)
    )
    store.con.execute(
        "DELETE FROM cross_market_incidents WHERE shock_end < ?",
        (moment - INCIDENT_RETENTION_SECONDS,)
    )
    store.con.commit()
    return added


def cached_headlines(store: StateStore, *, now: float | None = None) -> list[Headline]:
    moment = time.time() if now is None else float(now)
    ensure_tables(store)
    rows = store.con.execute(
        """SELECT dedupe_key, source, provider, title, published, link
           FROM cross_market_news
           WHERE published >= ? AND published <= ?
           ORDER BY published ASC LIMIT 500""",
        (moment - CACHE_RETENTION_SECONDS, moment + 30),
    ).fetchall()
    results = []
    for dedupe, source, provider, title, published, link in rows:
        # Dedupe key provider|id; reconstruct id for stable matching.
        item_id = dedupe.partition("|")[2]
        results.append(Headline(
            source=source, item_id=item_id,
            title=title, published=published, provider=provider, link=link,
        ))
    return results


def _first_seen(store: StateStore, headline: Headline | None) -> float | None:
    if headline is None:
        return None
    row = store.con.execute(
        "SELECT first_seen FROM cross_market_news WHERE dedupe_key=?",
        (headline.dedupe_key,),
    ).fetchone()
    return float(row[0]) if row else None


def _label(match: CatalystMatch, bar_end: float, first_seen: float | None) -> str:
    if not match.headline:
        return "NO_VERIFIED_PRE_EVENT_HEADLINE"
    if first_seen is not None and first_seen > bar_end:
        return "PRE_EVENT_PUBLICATION_DISCOVERED_LATE"
    return "TIMESTAMP_MATCH_ONLY"


def record_incident(
    store: StateStore, event: MarketShock, evidence: CatalystMatch, *, now: float
) -> None:
    ensure_tables(store)
    seen = _first_seen(store, evidence.headline)
    label = _label(evidence, event.bar_end, seen)
    news_key = evidence.headline.dedupe_key if evidence.headline else None
    published = evidence.headline.published if evidence.headline else None
    inserted = store.con.execute(
        """INSERT OR IGNORE INTO cross_market_incidents(
            event_key, shock_end, detected_at, provider, event_id,
            brent_ref, nq_ref, brent_move, nq_move, evidence_label,
            linked_news_key, link_published, link_first_seen, updated_at
        ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (event.key, event.bar_end, now, event.provider, event.event_id,
         event.brent_symbol, event.nasdaq_symbol, event.brent_change_pct,
         event.nasdaq_change_pct, label, news_key, published, seen, now),
    ).rowcount > 0
    if inserted:
        store.con.execute(
            """INSERT INTO cross_market_revisions(
                event_key, changed_at, previous_label, evidence_label,
                linked_news_key, link_published, link_first_seen
            ) VALUES (?, ?, NULL, ?, ?, ?, ?)""",
            (event.key, now, label, news_key, published, seen),
        )
    store.con.commit()


def reconcile_incidents(
    store: StateStore,
    *,
    now: float | None = None,
    notification=None,
    alert_callback=None,
) -> dict[str, int]:
    """Re-check publication chronology when provider headlines arrive late.

    Old claims are never erased: every change gets a revision. The first
    upgrade from unknown to a plausible pre-event publication may notify.
    """
    moment = time.time() if now is None else float(now)
    ensure_tables(store)
    from .notifier import alert_click, notify
    news = cached_headlines(store, now=moment)
    rows = store.con.execute(
        """SELECT event_key, shock_end, provider, event_id, brent_ref, nq_ref,
                  brent_move, nq_move, evidence_label, linked_news_key,
                  upgrade_alerted
           FROM cross_market_incidents
           WHERE shock_end BETWEEN ? AND ? ORDER BY shock_end DESC LIMIT 100""",
        (moment - RECHECK_WINDOW_SECONDS, moment),
    ).fetchall()
    out = {"checked": len(rows), "updated": 0, "notified": 0}
    for (key, t, provider, event_id, bref, nref, bmove, nmove,
         old_label, previous_news, upgrade_alerted) in rows:
        event = MarketShock(event_id, provider, t, bref, nref, bmove, nmove)
        match = match_catalyst(event, news)
        if match.headline is None:
            continue
        new_key = match.headline.dedupe_key
        first_seen = _first_seen(store, match.headline)
        next_label = _label(match, t, first_seen)
        if new_key == previous_news and next_label == old_label:
            continue
        # Do not downgrade an established pre-event report when today's
        # bounded news cache has temporarily lost it.
        store.con.execute(
            """UPDATE cross_market_incidents
               SET evidence_label=?, linked_news_key=?, link_published=?,
                   link_first_seen=?, updated_at=?
               WHERE event_key=?""",
            (next_label, new_key, match.headline.published, first_seen, moment, key),
        )
        store.con.execute(
            """INSERT INTO cross_market_revisions(
                event_key, changed_at, previous_label, evidence_label,
                linked_news_key, link_published, link_first_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (key, moment, old_label, next_label, new_key, match.headline.published, first_seen),
        )
        addition = (
            f"Tidsmatchad nyhet ({match.headline.provider}), publicerad "
            f"{match.lag_seconds}s före prisrörelsen, först observerad "
            f"{'EFTER' if first_seen is not None and first_seen > t else 'FÖRE'} rörelsen:\n"
            f"{match.headline.title}\n"
            "En möjlig katalysator; tidssambandet bevisar inte orsak."
        )
        store.con.execute(
            """UPDATE alerts SET body=?, link=?
               WHERE item_key=?""",
            (addition, normalize_news_link(match.headline.link), key),
        )
        out["updated"] += 1
        if previous_news is None and not upgrade_alerted:
            alert_key = key + ":CATALYST_UPDATE"
            saved = store.record_alert(
                item_key=alert_key,
                source="CROSS_MARKET_CATALYST_UPDATE",
                provider=match.headline.provider,
                headline="Ny tidsmatchad källa för Brent/Nasdaq-rörelse",
                body=addition,
                published=match.headline.published,
                link=normalize_news_link(match.headline.link),
                score=8, at=moment,
            )
            if saved:
                store.con.execute(
                    "UPDATE cross_market_incidents SET upgrade_alerted=1 WHERE event_key=?",
                    (key,),
                )
                if alert_callback:
                    try:
                        alert_callback(store.unread_alert_count())
                    except Exception:
                        logging.exception("cross-market evidence callback failed")
                sender = notification or (
                    lambda title, body: notify(
                        title, body, item_key=alert_key,
                        on_click=alert_click(store.path, alert_key, alert_callback),
                    )
                )
                if sender("Trade Alert · NY KATALYSATOR", addition):
                    out["notified"] += 1
        store.con.commit()
    return out
