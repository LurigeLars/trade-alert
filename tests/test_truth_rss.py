"""Fixture tests for the public third-party RSS adapter; zero live HTTP calls."""
import asyncio
import pathlib
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from trade_alert.app import run_loop
from trade_alert.config import Config
from trade_alert.state import StateStore
from trade_alert.truth_rss import (
    RSSPost, RSSResult, RSSUnavailable, parse_rss, read_rss_once,
)

T0 = datetime(2026, 10, 8, 16, 17, 0, tzinfo=timezone.utc).timestamp()


def fixture(post_id="11", text="Trump says US will not attack Iran before midterm election",
            pub="Thu, 08 Oct 2026 16:17:00 GMT"):
    return (f'<?xml version="1.0"?><rss version="2.0"><channel>'
            f"<title>Trump's Truth</title>"
            f"<item><title>{text}</title><description>{text}</description>"
            f"<link>https://www.trumpstruth.org/statuses/{post_id}</link>"
            f"<guid>truth-{post_id}</guid><pubDate>{pub}</pubDate></item>"
            f"</channel></rss>").encode()


class RSSParserTests(unittest.TestCase):
    def test_valid_rss_and_stable_identity(self):
        a = parse_rss(fixture())
        b = parse_rss(fixture())
        self.assertEqual(len(a), 1)
        self.assertEqual(a, b)
        self.assertEqual(a[0].published, T0)
        self.assertIn("will not attack Iran", a[0].text)

    def test_spoofed_link_and_malicious_entity_are_rejected(self):
        self.assertRaises(RSSUnavailable, parse_rss, b"<!DOCTYPE rss [<!ENTITY x 'a'>]><rss/>")
        self.assertRaises(RSSUnavailable, parse_rss, b"<html>not rss</html>")
        f = fixture().replace(b"www.trumpstruth.org", b"www.trumpstruth.org.evil.test")
        with self.assertRaises(RSSUnavailable):
            parse_rss(f)

    def test_missing_timestamp_fails_closed(self):
        with self.assertRaises(RSSUnavailable):
            parse_rss(fixture(pub="not a date"))


class RSSIntakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_initial_baseline_new_policy_alert_and_dedupe(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(pathlib.Path(td) / "state.db")
            initial = RSSResult(parse_rss(fixture()), "etag-a", None)
            updated = RSSResult(
                parse_rss(fixture()) + parse_rss(fixture("12")), "etag-b", None)
            calls = iter([initial, updated, updated])
            messages = []
            def fetch(**kwargs):
                return next(calls)
            try:
                cfg = Config()
                first = await read_rss_once(cfg, store, fetch=fetch,
                                            now=T0 + 10,
                                            notification=lambda *a: messages.append(a) or True)
                self.assertEqual(first["status"], "BASELINED")
                self.assertEqual(len(messages), 0)
                second = await read_rss_once(cfg, store, fetch=fetch, now=T0+45,
                                             notification=lambda *a: messages.append(a) or True)
                self.assertEqual(second["notified"], 1)
                self.assertEqual(store.unread_alert_count(), 1)
                self.assertIn("oberoende RSS", messages[0][1])
                self.assertIn("trumpstruth.org/statuses/12", store.recent_alerts()[0].link)
                third = await read_rss_once(cfg, store, fetch=fetch, now=T0+65,
                                            notification=lambda *a: self.fail("duplicate"))
                self.assertEqual(third["notified"], 0)
                self.assertEqual(store.get_meta("truth_rss_etag"), "etag-b")
            finally:
                store.close()

    async def test_old_items_and_non_market_posts_suppressed(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(pathlib.Path(td) / "state.db")
            store.set_meta("truth_rss_initialized", "yes")
            data = RSSResult(
                parse_rss(fixture("11")) +
                parse_rss(fixture("12", "Happy Birthday to everyone", "Thu, 08 Oct 2026 16:34:00 GMT")),
                None, None
            )
            try:
                result = await read_rss_once(
                    Config(), store, fetch=lambda **kw: data, now=T0 + 1800,
                    notification=lambda *args: self.fail("stale or irrelevant"))
                self.assertEqual(result["notified"], 0)
            finally:
                store.close()

    async def test_rss_notification_is_not_blocked_by_hanging_mcp_news(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(pathlib.Path(td) / "state.db")
            cfg = Config(breaking_inbox_enabled=False, truth_rss_enabled=True)
            calls = []
            stop = asyncio.Event()
            async def mocked_rss(*a, **kw):
                calls.append("rss")
                return {"status": "COMPLETE", "notified": 0}
            async def hanging_news(*a, **kw):
                await asyncio.sleep(4)
            try:
                with patch("trade_alert.app._run_news_loop", new=hanging_news), \
                     patch("trade_alert.app.read_rss_once", new=mocked_rss):
                    task = asyncio.create_task(run_loop(cfg, store, stop_event=stop))
                    await asyncio.sleep(0.16)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                self.assertEqual(calls, ["rss"])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
