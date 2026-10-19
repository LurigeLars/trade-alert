import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from trade_alert.config import Config
from trade_alert.market_correlation import MarketCorrelationError
from trade_alert.market_price import (
    parse_resident_snapshot,
    collect_resident_events,
    activate_if_resident,
)


T = 1792413360  # Current open one-minute bar.


def make_pane(symbol, previous, latest, *, delay=False):
    return {
        "success": True,
        "resolved_symbol": symbol,
        "resolution": "1",
        "quote": {
            "is_delay": delay,
            "age_at_retrieval_ms": 15000,
        },
        "metadata": {
            "instrument_type": "futures",
            "bar_time_is_period_start": True,
            "realtime_status": "realtime",
            "delay_minutes": None,
        },
        "current_bar": {
            "time": T,
            "close": latest,
        },
        "recent_bars": [
            {"time": T - 120, "close": previous},
            {"time": T - 60, "close": latest},
            {"time": T, "close": latest + 1},
        ],
    }


def snapshot():
    return {
        "success": True,
        "failed_count": 0,
        "missing": [],
        "snapshots": [
            make_pane("NYMEX:BZZ2026", 108.73, 108.09),
            make_pane("CME_MINI:NQ1!", 29688.25, 29746.75),
        ],
    }


def config():
    return Config(
        market_correlation_enabled=True,
        market_correlation_authorized_sources=("DTV_RESIDENT",),
    )


class MarketPriceTests(unittest.TestCase):
    def test_uses_closed_bars_only_and_utc_bar_end(self):
        events = parse_resident_snapshot(snapshot(), config(), now=T + 15)
        self.assertEqual(1, len(events))
        event = events[0]
        self.assertEqual("DTV_RESIDENT", event["provider"])
        self.assertEqual(T, int(__import__("datetime").datetime.fromisoformat(
            event["brent"]["bar_end"].replace("Z", "+00:00")).timestamp()))
        self.assertEqual(108.73, event["brent"]["previous_close"])
        self.assertEqual(108.09, event["brent"]["close"])

    def test_signal_must_not_use_incomplete_active_candle(self):
        s = snapshot()
        s["snapshots"][0]["recent_bars"][1]["close"] = 108.72
        self.assertEqual([], parse_resident_snapshot(s, config(), now=T + 15))

    def test_refuses_delay_stale_mismatch_missing_and_gaps(self):
        failures = []
        delayed = snapshot()
        delayed["snapshots"][0]["quote"]["is_delay"] = True
        failures.append(delayed)
        stale = snapshot()
        stale["snapshots"][1]["quote"]["age_at_retrieval_ms"] = 121000
        failures.append(stale)
        wrong = snapshot()
        wrong["snapshots"][0]["resolved_symbol"] = "TVC:UKOIL"
        failures.append(wrong)
        missing = snapshot()
        missing["missing"] = ["NYMEX:BZZ2026"]
        failures.append(missing)
        for v in failures:
            with self.subTest(scenario=failures.index(v)):
                with self.assertRaises(MarketCorrelationError):
                    parse_resident_snapshot(v, config(), now=T + 15)

    def test_missing_minute_never_emits_signal(self):
        gapped = snapshot()
        gapped["snapshots"][0]["recent_bars"][0]["time"] -= 60
        self.assertEqual([], parse_resident_snapshot(gapped, config(), now=T + 15))

    def test_refuses_stale_completed_minute(self):
        with self.assertRaises(MarketCorrelationError):
            parse_resident_snapshot(snapshot(), config(), now=T + 360)

    def test_requires_latest_quote_not_a_delayed_proxy(self):
        s = snapshot()
        s["snapshots"][1]["metadata"]["realtime_status"] = "delayed"
        with self.assertRaises(MarketCorrelationError):
            parse_resident_snapshot(s, config(), now=T + 15)


class MarketPriceAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def test_autoconfig_requires_exact_preexisting_worker_assignments(self):
        cfg = config()
        cfg.market_correlation_enabled = False
        workers = {
            "success": True,
            "entries": [
                {
                    "handle": "cross-brent-dec26-1m",
                    "symbol": "NYMEX:BZZ2026",
                    "timeframe": "1",
                    "assignment": {
                        "resolved_symbol": "NYMEX:BZZ2026",
                        "resolution": "1",
                    },
                },
                {
                    "handle": "cross-nasdaq-1m",
                    "symbol": "CME_MINI:NQ1!",
                    "timeframe": "1",
                    "assignment": {
                        "resolved_symbol": "CME_MINI:NQ1!",
                        "resolution": "1",
                    },
                },
            ],
        }
        with patch("trade_alert.market_price.call_json_tool",
                   new=AsyncMock(return_value=workers)), (
                patch("trade_alert.config.Config.save") as write):
            self.assertTrue(await activate_if_resident(cfg))
            write.assert_called_once()
        self.assertTrue(cfg.market_correlation_enabled)

        cfg.market_correlation_enabled = False
        workers["entries"][0]["assignment"]["resolved_symbol"] = "TVC:UKOIL"
        with patch("trade_alert.market_price.call_json_tool",
                   new=AsyncMock(return_value=workers)), (
                patch("trade_alert.config.Config.save") as write):
            self.assertFalse(await activate_if_resident(cfg))
            write.assert_not_called()

    async def test_calls_existing_dtv_resident_no_chart_switch(self):
        with patch(
            "trade_alert.market_price.call_json_tool",
            new=AsyncMock(return_value=snapshot()),
        ) as api:
            with patch("trade_alert.market_price.time.time", return_value=T + 15):
                hits = await collect_resident_events(config())
        self.assertEqual(1, len(hits))
        args = api.await_args.args
        self.assertEqual("realtime_snapshot", args[1])
        self.assertEqual(
            ["cross-brent-dec26-1m", "cross-nasdaq-1m"],
            api.await_args.args[2]["handles"],
        )


if __name__ == "__main__":
    unittest.main()
