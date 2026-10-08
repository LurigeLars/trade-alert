"""Offline regression tests for public direct Truth Social source."""
import asyncio
import json
import pathlib
import tempfile
import unittest
import urllib.error
from datetime import datetime, timezone
from unittest.mock import patch

from trade_alert.app import run_loop
from trade_alert.config import Config
from trade_alert.state import StateStore
from trade_alert.truth_direct import (
    ACCOUNT_ID, DirectPost, DirectResult, DirectUnavailable,
    _relevance, fetch_public_statuses, parse_statuses, read_direct_once,
)

T0 = datetime(2026, 10, 8, 16, 17, tzinfo=timezone.utc).timestamp()


def post(pid: str = "117123456789012345", acct: str = "realDonaldTrump",
         text: str = "We will not be attacking Iran before the elections",
         account_id: str = ACCOUNT_ID):
    return dict(
        id=pid,
        created_at="2026-10-08T16:17:00Z",
        visibility="public",
        account={"id": account_id, "acct": acct},
        content=f"<p>{text}</p>",
        url=f"https://malicious.invalid/redirect/{pid}",
    )


def fixture(*posts):
    return json.dumps(list(posts)).encode("utf-8")


class DirectParsingTests(unittest.TestCase):
    def test_canonical_identity_and_text(self):
        rows = parse_statuses(fixture(post()), fetched_at=T0+7).posts
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].published, T0)
        self.assertEqual(rows[0].text, "We will not be attacking Iran before the elections")
        self.assertEqual(rows[0].link,
                         "https://truthsocial.com/@realDonaldTrump/117123456789012345")

    def test_wrong_account_private_bad_id_and_invalid_json_are_rejected(self):
        p = post(acct="impostor")
        self.assertEqual(parse_statuses(fixture(p), fetched_at=T0).posts, ())
        self.assertEqual(parse_statuses(fixture(post(account_id="2222")),
                                        fetched_at=T0).posts, ())
        z = post()
        z["visibility"] = "private"
        self.assertEqual(parse_statuses(fixture(z), fetched_at=T0).posts, ())
        with self.assertRaises(DirectUnavailable):
            parse_statuses(b'{"error":"not authenticated"}', fetched_at=T0)
        with self.assertRaises(DirectUnavailable):
            parse_statuses(b"not json", fetched_at=T0)

    def test_html_is_inert_text_and_deduplicated(self):
        x = post(text="Iran <b>oil</b> talks")
        r = parse_statuses(fixture(x, x), fetched_at=T0).posts
        self.assertEqual(len(r), 1)
        self.assertEqual(r[0].text, "Iran oil talks")

    def test_blocked_http_is_reported_without_internal_retry(self):
        class FakeOpener:
            def open(self, *args, **kwargs):
                raise urllib.error.HTTPError(
                    "https://truthsocial.com", 403, "Forbidden", {}, None)
        with patch("trade_alert.truth_direct.urllib.request.build_opener",
                   return_value=FakeOpener()):
            with self.assertRaises(DirectUnavailable) as ctx:
                fetch_public_statuses()
        self.assertTrue(ctx.exception.blocked)
        self.assertIn("403", str(ctx.exception))

    def test_market_keywords(self):
        self.assertGreaterEqual(_relevance("Iran attack pause"), 4)
        self.assertGreaterEqual(_relevance("Important tariff announcement"), 4)
        self.assertEqual(_relevance("Happy birthday"), 0)


class DirectIntakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_baseline_new_post_and_no_duplicate(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(pathlib.Path(tmp) / "state.db")
            first_id = "117123456789012345"
            second_id = "117123456789012346"
            first = DirectResult((
                DirectPost(first_id, "Iran attack pause", T0, "https://truthsocial.com/a"),
            ), fetched_at=T0+8)
            second = DirectResult(first.posts + (
                DirectPost(second_id, "Iran negotiations continue", T0+10,
                           "https://truthsocial.com/b"),), fetched_at=T0+11)
            it = iter((first, second, second))
            notifications = []
            def fetch():
                return next(it)
            try:
                config = Config()
                a = await read_direct_once(
                    config, store, fetch=fetch, now=T0+8,
                    notification=lambda *args: notifications.append(args) or True)
                self.assertEqual(a["status"], "BASELINED")
                self.assertEqual(a["notified"], 0)
                b = await read_direct_once(
                    config, store, fetch=fetch, now=T0+20,
                    notification=lambda *args: notifications.append(args) or True)
                self.assertEqual(b["notified"], 1)
                self.assertEqual(store.unread_alert_count(), 1)
                self.assertIn("Truth Social", notifications[0][1])
                c = await read_direct_once(
                    config, store, fetch=fetch, now=T0+35,
                    notification=lambda *_: self.fail("duplicate"))
                self.assertEqual(c["notified"], 0)
            finally:
                store.close()

    async def test_old_posts_never_fire(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(pathlib.Path(td) / "state.db")
            store.set_meta("truth_direct_initialized", "yes")
            try:
                v = DirectResult((DirectPost(
                    "117123456789012345", "Iran war",
                    T0, "https://truthsocial.com/example"),), fetched_at=T0+600)
                a = await read_direct_once(Config(), store, fetch=lambda: v,
                                           now=T0+600,
                                           notification=lambda *_: self.fail("old"))
                self.assertEqual(a["notified"], 0)
            finally:
                store.close()

    async def test_direct_runs_even_while_news_loop_waits(self):
        with tempfile.TemporaryDirectory() as td:
            store = StateStore(pathlib.Path(td) / "state.db")
            config = Config(truth_rss_enabled=False, breaking_inbox_enabled=False,
                            truth_direct_enabled=True)
            calls = []
            async def slow_news(*args, **kwargs):
                await asyncio.sleep(10)
            async def direct(*args, **kwargs):
                calls.append("direct")
                return {"status": "COMPLETE"}
            try:
                with patch("trade_alert.app._run_news_loop", new=slow_news), \
                     patch("trade_alert.app.read_direct_once", new=direct):
                    task = asyncio.create_task(run_loop(config, store))
                    await asyncio.sleep(0.1)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                self.assertEqual(calls, ["direct"])
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
