import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from trade_alert.config import Config
from trade_alert.market_correlation import (
    MarketCorrelationError, match_catalyst, parse_market_shock,
    process_market_incidents,
)
from trade_alert.news import Headline
from trade_alert.state import StateStore


MOMENT = datetime(2026, 10, 19, 10, 40, tzinfo=timezone.utc).timestamp()
STAMP = "2026-10-19T10:39:00Z"


def setup_config():
    return Config(
        market_correlation_enabled=True,
        market_correlation_authorized_sources=("TRADE_SPINE_LOCAL",),
        market_correlation_brent_symbol="NYMEX:BZZ2026",
        market_correlation_nasdaq_symbol="CME_MINI:NQ1!",
    )


def payload(event_id="incident-1"):
    return {
        "event_id": event_id,
        "provider": "TRADE_SPINE_LOCAL",
        "bar_seconds": 60,
        "realtime": True,
        "delayed": False,
        "brent": {
            "symbol": "NYMEX:BZZ2026",
            "bar_end": STAMP,
            "previous_close": 108.73,
            "close": 108.09,
        },
        "nasdaq": {
            "symbol": "CME_MINI:NQ1!",
            "bar_end": STAMP,
            "previous_close": 29688.25,
            "close": 29746.75,
        },
    }


def article(title, t, provider="Reuters", link="https://www.reuters.com/world/story"):
    return Headline(
        source="DTV_NEWS_FLOW",
        item_id=str(t),
        provider=provider,
        title=title,
        published=t,
        link=link,
    )


class CorrelationTests(unittest.TestCase):
    def test_accepts_only_synchronized_fresh_confirmed_realtime_bars(self):
        event = parse_market_shock(payload(), setup_config(), now=MOMENT)
        self.assertLess(event.brent_change_pct, -0.5)
        self.assertGreater(event.nasdaq_change_pct, 0.15)
        self.assertEqual(event.bar_end, datetime.fromisoformat(STAMP.replace("Z", "+00:00")).timestamp())

    def test_rejects_wrong_instrument_source_and_time(self):
        for key, value in [
            ("provider", "UNAPPROVED"),
            ("realtime", False),
            ("delayed", True),
            ("bar_seconds", 300),
        ]:
            with self.subTest(key=key):
                x = payload()
                x[key] = value
                with self.assertRaises(MarketCorrelationError):
                    parse_market_shock(x, setup_config(), now=MOMENT)
        for leg, field, value in [
            ("brent", "symbol", "TVC:UKOIL"),
            ("nasdaq", "bar_end", "2026-10-19T10:37:00Z"),
            ("brent", "previous_close", 0),
            ("brent", "close", 109.0),
            ("nasdaq", "close", 29000.0),
        ]:
            with self.subTest(leg=leg, field=field):
                x = payload()
                x[leg][field] = value
                with self.assertRaises(MarketCorrelationError):
                    parse_market_shock(x, setup_config(), now=MOMENT)
        with self.assertRaises(MarketCorrelationError):
            parse_market_shock(payload(), setup_config(), now=MOMENT+400)

    def test_matches_earliest_valid_primary_publication_before_event(self):
        shock = parse_market_shock(payload(), setup_config(), now=MOMENT)
        a = article("Iran oil supply disruption enters talks", shock.bar_end - 700)
        b = article("Oil prices sink after Iran ceasefire", shock.bar_end - 150)
        later = article("Oil tumbles on Trump statement", shock.bar_end + 4)
        aggregator = article(
            "Oil sanctions in Iran",
            shock.bar_end - 900,
            provider="Rumour Blog",
        )
        match = match_catalyst(shock, [later, b, aggregator, a])
        self.assertEqual("TIMESTAMP_MATCH_ONLY", match.label)
        self.assertEqual(a, match.headline)
        self.assertEqual(700, match.lag_seconds)

    def test_after_event_old_irrelevant_or_unlinked_news_cannot_be_trigger(self):
        shock = parse_market_shock(payload(), setup_config(), now=MOMENT)
        candidates = [
            article("Iran oil talks", shock.bar_end + 1),
            article("Iran oil talks", shock.bar_end - 1900),
            article("AI software investment boom", shock.bar_end - 100),
            article("Iran oil sanctions", shock.bar_end - 100, link="http://example.com"),
        ]
        match = match_catalyst(shock, candidates)
        self.assertIsNone(match.headline)
        self.assertEqual("NO_VERIFIED_PRE_EVENT_HEADLINE", match.label)

    def test_inbox_dedupe_and_no_false_causal_claim(self):
        with tempfile.TemporaryDirectory() as temp:
            store = StateStore(Path(temp)/"alerts.sqlite")
            folder = Path(temp)/"events"
            folder.mkdir()
            (folder/"a.json").write_text(json.dumps(payload()), encoding="utf-8")
            messages = []
            try:
                result = process_market_incidents(
                    setup_config(), store, [], directory=folder, now=MOMENT,
                    notification=lambda title, body: messages.append((title,body)) or True,
                )
                self.assertEqual(1, result["accepted"])
                self.assertEqual(1, result["notified"])
                self.assertEqual(1, store.unread_alert_count())
                self.assertIn("Orsak OKÄND", messages[0][1])
                self.assertEqual([], list(folder.glob("*.json")))
                (folder/"b.json").write_text(json.dumps(payload()), encoding="utf-8")
                second = process_market_incidents(
                    setup_config(), store, [], directory=folder, now=MOMENT,
                    notification=lambda *args: True,
                )
                self.assertEqual(0, second["accepted"])
                self.assertEqual(1, second["suppressed"])
            finally:
                store.close()

    def test_disabled_by_default_without_producer(self):
        with tempfile.TemporaryDirectory() as temp:
            store = StateStore(Path(temp)/"alerts.sqlite")
            try:
                self.assertFalse(Config().market_correlation_enabled)
                self.assertEqual(0, process_market_incidents(
                    Config(), store, [], directory=Path(temp)/"events",
                    now=MOMENT,
                )["accepted"])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
