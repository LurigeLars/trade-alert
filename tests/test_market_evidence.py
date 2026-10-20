import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from trade_alert.config import Config
from trade_alert.market_correlation import process_market_incidents
from trade_alert.market_evidence import (
    cache_headlines, cached_headlines, reconcile_incidents,
)
from trade_alert.news import Headline
from trade_alert.state import StateStore


EVENT_TIME = datetime(2026, 10, 19, 10, 39, tzinfo=timezone.utc).timestamp()
PAST = datetime.fromtimestamp(EVENT_TIME, timezone.utc).isoformat().replace("+00:00", "Z")


def cfg():
    return Config(
        market_correlation_enabled=True,
        market_correlation_authorized_sources=("DTV_RESIDENT",),
    )


def shock():
    return {
        "event_id": "incident-1",
        "provider": "DTV_RESIDENT",
        "bar_seconds": 60,
        "realtime": True,
        "delayed": False,
        "brent": {
            "symbol": "NYMEX:BZZ2026",
            "bar_end": PAST,
            "previous_close": 108.73,
            "close": 108.09,
        },
        "nasdaq": {
            "symbol": "CME_MINI:NQ1!",
            "bar_end": PAST,
            "previous_close": 29688,
            "close": 29746.75,
        },
    }


def news(pub, *, link="https://www.reuters.com/world/iran-oil-shipping", text="Brent oil prices fall on Iran deal"):
    return Headline(
        source="DTV_NEWS_FLOW",
        item_id="r:1",
        provider="Reuters",
        title=text,
        published=pub,
        link=link,
    )


class MarketEvidenceTests(unittest.TestCase):
    def test_backfilled_pre_event_news_upgrades_unknown_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.db")
            try:
                result = process_market_incidents(
                    cfg(), store, [], records=[shock()],
                    now=EVENT_TIME + 20, notification=lambda *_: True,
                )
                self.assertEqual(1, result["accepted"])
                row = store.con.execute(
                    "SELECT evidence_label FROM cross_market_incidents"
                ).fetchone()
                self.assertEqual("NO_VERIFIED_PRE_EVENT_HEADLINE", row[0])
                article = news(EVENT_TIME - 120)
                first_seen = EVENT_TIME + 70
                self.assertEqual(1, cache_headlines(
                    store, [article], now=first_seen,
                ))
                updates = []
                found = reconcile_incidents(
                    store, now=first_seen, notification=lambda *v: updates.append(v) or True,
                )
                self.assertEqual(1, found["updated"])
                self.assertEqual(1, found["notified"])
                self.assertEqual(1, len(updates))
                row = store.con.execute(
                    "SELECT evidence_label, link_first_seen FROM cross_market_incidents"
                ).fetchone()
                self.assertEqual("PRE_EVENT_PUBLICATION_DISCOVERED_LATE", row[0])
                self.assertEqual(first_seen, row[1])
                count = store.con.execute(
                    "SELECT COUNT(*) FROM cross_market_revisions"
                ).fetchone()[0]
                self.assertEqual(2, count)
                again = reconcile_incidents(
                    store, now=first_seen + 1,
                    notification=lambda *_: self.fail("duplicate update"),
                )
                self.assertEqual(0, again["notified"])
                self.assertEqual(0, again["updated"])
            finally:
                store.close()

    def test_news_published_after_shock_cannot_be_retroactive_trigger(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.db")
            try:
                process_market_incidents(
                    cfg(), store, [], records=[shock()],
                    now=EVENT_TIME + 20, notification=lambda *_: True,
                )
                cache_headlines(
                    store, [news(EVENT_TIME + 1)], now=EVENT_TIME + 60,
                )
                found = reconcile_incidents(store, now=EVENT_TIME + 60)
                self.assertEqual(0, found["updated"])
            finally:
                store.close()

    def test_cache_preserves_first_seen_when_headline_replayed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.db")
            try:
                candidate = news(EVENT_TIME - 20)
                t = EVENT_TIME - 10
                self.assertEqual(1, cache_headlines(store, [candidate], now=t))
                self.assertEqual(0, cache_headlines(store, [candidate], now=t + 70))
                matches = cached_headlines(store, now=t + 80)
                self.assertEqual(1, len(matches))
                first_seen = store.con.execute(
                    "SELECT first_seen FROM cross_market_news"
                ).fetchone()[0]
                self.assertEqual(t, first_seen)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
