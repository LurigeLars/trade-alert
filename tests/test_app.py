import asyncio
import pathlib
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from trade_alert.app import (
    _dtv_since_with_overlap, _collect, _run_news_loop,
    _run_market_correlation_loop, run_once, OFFICIAL_TRADINGVIEW_DISABLED,
)
from trade_alert.config import Config
from trade_alert.news import Headline, DTVNewsBatch, DTVWatchlistContext
from trade_alert.market_price import StaleResidentPriceError
from trade_alert.state import StateStore


class AppTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_resident_source_sets_distinct_health_without_alert(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(pathlib.Path(tmp) / "state.db")
            stop = asyncio.Event()
            async def stop_after_poll(_seconds, _stop_event=None):
                stop.set()
            try:
                with (
                    patch("trade_alert.app.collect_resident_events",
                          new=AsyncMock(side_effect=StaleResidentPriceError(
                              "DTV resident quote timestamp stale"))),
                    patch("trade_alert.app._sleep_interruptible",
                          side_effect=stop_after_poll),
                ):
                    await _run_market_correlation_loop(
                        Config(market_correlation_enabled=True),
                        store, stop_event=stop,
                    )
                self.assertEqual("STALE", store.get_meta("cross_market_price_status"))
                self.assertEqual(
                    "DTV resident quote timestamp stale",
                    store.get_meta("cross_market_price_last_error"),
                )
                self.assertIsNone(store.get_meta("cross_market_price_last_ok"))
                self.assertEqual(0, store.unread_alert_count())
            finally:
                store.close()

    async def test_health_text_distinguishes_stale_from_missing_and_active(self):
        cfg = Config(market_correlation_enabled=True)
        responses = []
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(pathlib.Path(tmp) / "state.db")
            try:
                for source_status, expected in (
                    ("STALE", "Väntar på färska Brent/Nasdaq-priser"),
                    ("DEGRADED", "Degraderad · Brent/Nasdaq prisdata saknas"),
                    ("ACTIVE", "Aktiv · Brent/Nasdaq + DTV News Flow"),
                ):
                    store.set_meta("cross_market_price_status", source_status)
                    if source_status == "ACTIVE":
                        store.set_meta("cross_market_price_last_ok", str(time.time()))
                    stop = asyncio.Event()
                    async def stop_after_poll(_seconds, _stop_event=None):
                        stop.set()
                    with (
                        patch("trade_alert.app.run_once",
                              new=AsyncMock(return_value={
                                  "fresh": 0, "notified": 0,
                                  "dtv_ok": True, "official_ok": False,
                              })),
                        patch("trade_alert.app._sleep_interruptible",
                              side_effect=stop_after_poll),
                    ):
                        await _run_news_loop(
                            cfg, store, stop_event=stop,
                            status_callback=lambda text, health: responses.append((text, health)),
                        )
                    self.assertEqual(expected, responses[-1][0])
                    self.assertEqual("waiting" if source_status != "ACTIVE" else "ok", responses[-1][1])
            finally:
                store.close()

    async def test_official_provider_never_called_even_with_old_local_config(self):
        self.assertTrue(OFFICIAL_TRADINGVIEW_DISABLED)
        context = DTVWatchlistContext(
            watchlist_id="123", name="test", symbols=("ICEEUR:BRN1!",),
            auto_discovered=False,
        )
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(pathlib.Path(tmp) / "state.db")
            try:
                old_config = Config(official_symbols=("ICEEUR:BRN1!", "NYMEX:RB1!"))
                with (
                    patch("trade_alert.app._resolve_dtv_context", new=AsyncMock(return_value=context)),
                    patch("trade_alert.app.fetch_dtv_news", new=AsyncMock(return_value=DTVNewsBatch((), context, True))),
                    patch("trade_alert.app.fetch_official_news", new=AsyncMock()) as official,
                ):
                    items, dtv_ok, official_ok, _ = await _collect(
                        old_config, store, include_official=True, dtv_since=None,
                    )
                official.assert_not_awaited()
                self.assertEqual([], items)
                self.assertTrue(dtv_ok)
                self.assertFalse(official_ok)
            finally:
                store.close()

    def test_dtv_cursor_replays_overlap_window(self):
        self.assertEqual(
            "2026-10-08T22:30:00+00:00",
            _dtv_since_with_overlap("2026-10-08T23:30:00+00:00", 3600),
        )

    async def test_qualifying_signal_is_persisted_and_updates_unread_callback(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(pathlib.Path(tmp) / "state.db")
            item = Headline(
                source="TV:ICEEUR:BRN1!",
                item_id="story-1",
                title="Oil rises after Iran supply disruption",
                published=time.time(),
                provider="Reuters",
                link="https://example.test/story-1",
            )
            callback_counts = []
            try:
                with patch(
                    "trade_alert.app._collect",
                    new=AsyncMock(return_value=([item], False, True, False)),
                ), patch("trade_alert.app.notify", return_value=True) as notification:
                    result = await run_once(
                        Config(),
                        store,
                        alert_callback=callback_counts.append,
                    )

                self.assertEqual(1, result["notified"])
                self.assertEqual([1], callback_counts)
                self.assertEqual(1, store.unread_alert_count())
                alerts = store.recent_alerts()
                self.assertEqual("Oil rises after Iran supply disruption", alerts[0].headline)
                self.assertEqual("Reuters", alerts[0].provider)
                self.assertEqual(item.key, notification.call_args.kwargs["item_key"])
                with patch("trade_alert.notifier.webbrowser.open_new_tab", return_value=True) as browser:
                    self.assertTrue(notification.call_args.kwargs["on_click"]())
                browser.assert_called_once_with("https://example.test/story-1")
                self.assertEqual([1, 0], callback_counts)
                self.assertEqual(0, store.unread_alert_count())
            finally:
                store.close()

    async def test_notification_backend_failure_still_leaves_unread_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(pathlib.Path(tmp) / "state.db")
            item = Headline(
                source="TV:ICEEUR:BRN1!",
                item_id="story-2",
                title="Brent supply outage hits exports",
                published=time.time(),
                provider="Reuters",
            )
            try:
                with patch(
                    "trade_alert.app._collect",
                    new=AsyncMock(return_value=([item], False, True, False)),
                ), patch("trade_alert.app.notify", return_value=False):
                    result = await run_once(Config(), store)

                self.assertEqual(0, result["notified"])
                self.assertEqual(1, store.unread_alert_count())
            finally:
                store.close()

    async def test_existing_history_row_does_not_send_another_toast(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(pathlib.Path(tmp) / "state.db")
            item = Headline(source="DTV_NEWS_FLOW", item_id="retained",
                            title="Oil supply outage", published=time.time())
            try:
                store.record_alert(item_key=item.key, source=item.source,
                                   headline=item.title, body="body", score=4)
                with (
                    patch("trade_alert.app._collect", new=AsyncMock(
                        return_value=([item], True, False, True))),
                    patch("trade_alert.app.notify") as notification,
                ):
                    result = await run_once(Config(), store)
                self.assertEqual(0, result["notified"])
                notification.assert_not_called()
                self.assertEqual(1, store.unread_alert_count())
            finally:
                store.close()

    async def test_cross_source_duplicate_item_alerts_only_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(pathlib.Path(tmp) / "state.db")
            published = time.time()
            dtv = Headline(
                source="DTV_NEWS_FLOW",
                item_id="te_news:590623:0",
                title="Oil Prices Ease on Trump remarks about Iran",
                published=published,
                provider="Trading Economics",
            )
            official = Headline(
                source="TV:ICEEUR:BRN1!",
                item_id="te_news:590623:0",
                title="Brent Eases on Trump remarks about Iran",
                published=published,
                provider="Trading Economics",
            )
            try:
                with patch(
                    "trade_alert.app._collect",
                    new=AsyncMock(return_value=([dtv, official], True, True, True)),
                ), patch("trade_alert.app.notify", return_value=True) as mocked_notify:
                    result = await run_once(Config(), store)

                self.assertEqual(1, result["notified"])
                self.assertEqual(1, store.unread_alert_count())
                self.assertEqual(1, mocked_notify.call_count)
                self.assertTrue(store.seen_item("trading economics|te_news:590623:0"))
            finally:
                store.close()

    async def test_dtv_observation_is_recorded_before_seen_dedupe(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(pathlib.Path(tmp) / "state.db")
            item = Headline(
                source="DTV_NEWS_FLOW",
                item_id="story-observed",
                title="Oil rises after Iran supply disruption",
                published=time.time(),
                provider="Reuters",
            )
            store.mark_seen(item.key, at=time.time() - 10)
            store.mark_seen_item(item.dedupe_key, at=time.time() - 10)
            try:
                with patch(
                    "trade_alert.app._collect",
                    new=AsyncMock(return_value=([item], True, False, True)),
                ), patch("trade_alert.app.notify", return_value=True) as mocked_notify:
                    result = await run_once(Config(), store, include_official=False)

                self.assertEqual(0, result["notified"])
                mocked_notify.assert_not_called()
                self.assertIsNotNone(
                    store.source_first_seen(item.dedupe_key, "DTV_NEWS_FLOW")
                )
            finally:
                store.close()

    async def test_first_dtv_news_flow_cycle_baselines_old_broad_headlines(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(pathlib.Path(tmp) / "state.db")
            old_item = Headline(
                source="DTV_NEWS_FLOW",
                item_id="old-oil",
                title="Oil rises after Iran supply disruption",
                published=time.time() - 3600,
                provider="Reuters",
            )
            store.mark_initialized()
            try:
                with patch(
                    "trade_alert.app._collect",
                    new=AsyncMock(return_value=([old_item], True, True, True)),
                ), patch("trade_alert.app.notify", return_value=True) as mocked_notify:
                    result = await run_once(Config(), store)

                self.assertEqual(0, result["notified"])
                mocked_notify.assert_not_called()
                self.assertIsNotNone(store.get_meta("dtv_news_flow_initialized_at"))
                self.assertTrue(store.seen(old_item.key))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
