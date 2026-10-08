import asyncio
import json
import pathlib
import tempfile
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

from trade_alert.breaking import poll_breaking_inbox
from trade_alert.config import Config
from trade_alert.news import Headline, relevance_score
from trade_alert.state import StateStore
from trade_alert.app import run_loop

TRUTH_SOURCE = "TRUTHSOCIAL_REALDONALDTRUMP"
POST_ID = "115555555555555555"


def record(now):
    return {
        "source_id": TRUTH_SOURCE,
        "event_id": POST_ID,
        "headline": "We are having productive discussions with Iran; no attacks prior to midterms",
        "url": f"https://truthsocial.com/@realDonaldTrump/posts/{POST_ID}",
        "published_at": datetime.fromtimestamp(now - 6, tz=timezone.utc).isoformat(),
        "acquisition": "LICENSED",
    }


class BreakingAlertTests(unittest.TestCase):
    def test_approved_relay_emits_immediate_alert_with_history_and_dedupe(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp)
            inbox = path / "inbox"
            inbox.mkdir()
            store = StateStore(path / "state.db")
            cfg = Config(breaking_authorized_sources=(TRUTH_SOURCE,))
            now = time.time()
            notifications = []
            try:
                (inbox / "1.json").write_text(json.dumps(record(now)))
                result = poll_breaking_inbox(
                    cfg, store, directory=inbox, at=now,
                    notification=lambda t,b: notifications.append((t,b)) or True)
                self.assertEqual(result["notified"], 1)
                self.assertEqual(result["accepted"], 1)
                self.assertIn("Iran", notifications[0][1])
                self.assertEqual(len(store.recent_alerts()), 1)
                self.assertEqual(store.unread_alert_count(), 1)
                self.assertEqual(list(inbox.glob("*.json")), [])
                (inbox / "2.json").write_text(json.dumps(record(now)))
                replay = poll_breaking_inbox(cfg, store, directory=inbox, at=now,
                                             notification=lambda *_: self.fail("duplicate"))
                self.assertEqual(replay["notified"], 0)
            finally:
                store.close()

    def test_unapproved_source_never_emits_alert(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp)
            inbox = path / "inbox"
            inbox.mkdir()
            store = StateStore(path / "state.db")
            try:
                (inbox / "post.json").write_text(json.dumps(record(time.time())))
                with patch("trade_alert.breaking.notify") as notify:
                    result = poll_breaking_inbox(Config(), store, directory=inbox)
                self.assertEqual(result["rejected"], 1)
                notify.assert_not_called()
                self.assertEqual(store.unread_alert_count(), 0)
            finally:
                store.close()

    def test_forged_url_and_stale_events_rejected_or_baselined(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp)
            inbox = path / "inbox"
            inbox.mkdir()
            store = StateStore(path / "state.db")
            cfg = Config(breaking_authorized_sources=(TRUTH_SOURCE,))
            try:
                now = time.time()
                bad = record(now)
                bad["url"] = "https://truthsocial.com.evil.invalid/@realDonaldTrump/posts/" + POST_ID
                (inbox / "1.json").write_text(json.dumps(bad))
                outcome = poll_breaking_inbox(cfg, store, directory=inbox, at=now)
                self.assertEqual(outcome["rejected"], 1)
                old = record(now - 600)
                (inbox / "2.json").write_text(json.dumps(old))
                outcome = poll_breaking_inbox(cfg, store, directory=inbox, at=now)
                self.assertEqual(outcome["stale"], 1)
                self.assertEqual(store.unread_alert_count(), 0)
            finally:
                store.close()

    def test_us_iran_statement_matches_without_oil_keyword(self):
        item = Headline(
            source="DTV_NEWS_FLOW", item_id="recent", published=time.time(),
            title="Trump says US will not attack Iran before midterm elections"
        )
        self.assertGreaterEqual(relevance_score(item), 4)
        other = Headline(source="DTV_NEWS_FLOW", item_id="other",
                         title="President says markets are open for discussion",
                         published=time.time())
        self.assertEqual(relevance_score(other), 0)


class IndependentBreakingLoop(unittest.IsolatedAsyncioTestCase):
    async def test_breaking_loop_is_independent_of_slow_news_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp)
            store = StateStore(path / "state.db")
            now = time.time()
            event = record(now)
            inbox = path / "breaking"
            inbox.mkdir()
            (inbox / "incoming.json").write_text(json.dumps(event))
            cfg = Config(breaking_inbox_enabled=True, breaking_poll_seconds=0.2,
                         breaking_authorized_sources=(TRUTH_SOURCE,),
                         truth_direct_enabled=False)
            stop = asyncio.Event()
            notifications = []
            # Patch only inbox location, not intake validation. Network fetch
            # is blocked but a separate 0.2s task must still show the alert.
            async def hanging_news(*args, **kwargs):
                await asyncio.sleep(2)
                return {"fresh":0, "notified":0, "dtv_ok":False,
                        "official_ok":False}
            try:
                with patch("trade_alert.app.run_once", new=hanging_news), \
                     patch("trade_alert.breaking.inbox_path", return_value=inbox), \
                     patch("trade_alert.breaking.notify",
                           side_effect=lambda t,b: notifications.append(b) or True):
                    task = asyncio.create_task(run_loop(cfg, store, stop_event=stop))
                    await asyncio.sleep(0.55)
                    stop.set()
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                self.assertEqual(len(notifications), 1)
                self.assertEqual(store.unread_alert_count(), 1)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
