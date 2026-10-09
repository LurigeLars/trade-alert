import pathlib
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from trade_alert.app import _dtv_since_with_overlap, run_once
from trade_alert.config import Config
from trade_alert.news import Headline
from trade_alert.state import StateStore


class AppTests(unittest.IsolatedAsyncioTestCase):
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
                ), patch("trade_alert.app.notify", return_value=True):
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
