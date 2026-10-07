import pathlib
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from trade_alert.app import run_once
from trade_alert.config import Config
from trade_alert.news import Headline
from trade_alert.state import StateStore


class AppTests(unittest.IsolatedAsyncioTestCase):
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
                    new=AsyncMock(return_value=([item], False, True)),
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
                    new=AsyncMock(return_value=([item], False, True)),
                ), patch("trade_alert.app.notify", return_value=False):
                    result = await run_once(Config(), store)

                self.assertEqual(0, result["notified"])
                self.assertEqual(1, store.unread_alert_count())
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
