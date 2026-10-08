"""Chrome local-file relay never assumes an unverified message is genuine."""
import json
import pathlib
import tempfile
import time
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from trade_alert.chrome_feed import poll_browser_feed
from trade_alert.config import Config
from trade_alert.state import StateStore

ACCOUNT = "107780257626128497"
ID1 = "117406186276133332"
ID2 = "117406359223020085"


def row(post_id, published, *, text="Trump will not attack Iran", account=ACCOUNT,
        media=None):
    return {
        "id": post_id,
        "created_at": datetime.fromtimestamp(
            published, timezone.utc).isoformat().replace("+00:00", "Z"),
        "visibility": "public",
        "account": {"id": account, "username": "realDonaldTrump",
                    "acct": "realDonaldTrump"},
        "content": "<p>" + text + "</p>" if text else "",
        "media_attachments": media or []
    }


def emit(folder, payload, *, name=None):
    path = folder / (name or ("post-" + str(payload["id"]) + ".json"))
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


class ChromeBridgeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = pathlib.Path(self.tmp.name)
        self.folder = self.root / "Chrome"
        self.folder.mkdir()
        self.store = StateStore(self.root / "state.db")
        self.addCleanup(self.store.close)
        self.config = Config(chrome_bridge_enabled=True,
                             truth_direct_enabled=False, truth_rss_enabled=False)
        self.now = time.time()

    def test_fresh_market_post_alert_and_duplicate_suppression(self):
        notices = []
        emit(self.folder, row(ID1, self.now - 8))
        a = poll_browser_feed(self.config, self.store, directory=self.folder,
                              at=self.now,
                              notification=lambda *x: notices.append(x) or True)
        self.assertEqual(a["alerts"], 1)
        self.assertEqual(a["notified"], 1)
        self.assertIn("Iran", notices[0][1])
        self.assertEqual(len(self.store.recent_alerts()), 1)
        self.assertEqual(list(self.folder.iterdir()), [])
        emit(self.folder, row(ID1, self.now - 8))
        b = poll_browser_feed(self.config, self.store, directory=self.folder,
                              at=self.now, notification=lambda *_: self.fail("duplicate"))
        self.assertEqual(b["duplicates"], 1)
        self.assertEqual(b["alerts"], 0)

    def test_wrong_account_and_id_mismatch_rejected(self):
        emit(self.folder, row(ID1, self.now - 4, account="not-the-account"))
        emit(self.folder, row(ID2, self.now - 4), name=f"post-{ID1}.json")
        # Both attempted uses of the same filename become separate checks.
        a = poll_browser_feed(self.config, self.store, directory=self.folder, at=self.now)
        self.assertEqual(a["rejected"], 1)
        emit(self.folder, row(ID1, self.now - 4, account="not-the-account"))
        b = poll_browser_feed(self.config, self.store, directory=self.folder, at=self.now)
        self.assertEqual(b["rejected"], 1)
        self.assertEqual(self.store.unread_alert_count(), 0)

    def test_old_and_non_market_items_suppressed(self):
        emit(self.folder, row(ID1, self.now - 600))
        emit(self.folder, row(ID2, self.now - 9, text="Happy birthday"))
        z = poll_browser_feed(self.config, self.store, directory=self.folder, at=self.now)
        self.assertEqual(z["stale"], 1)
        self.assertEqual(z["alerts"], 0)
        self.assertEqual(self.store.unread_alert_count(), 0)

    def test_media_only_is_not_misclassified_as_text(self):
        emit(self.folder, row(ID1, self.now - 3, text="",
                              media=[{"type":"image"}]))
        a = poll_browser_feed(self.config, self.store, directory=self.folder, at=self.now)
        self.assertEqual(a["alerts"], 0)
        self.assertTrue(self.store.seen("TRUTH_PUBLIC:" + ID1))

    def test_config_opt_in_and_rejection_of_oversize(self):
        emit(self.folder, row(ID1, self.now - 4))
        off = Config(chrome_bridge_enabled=False)
        a = poll_browser_feed(off, self.store, directory=self.folder, at=self.now)
        self.assertEqual(a["files"], 0)
        self.assertEqual(len(list(self.folder.iterdir())), 1)
        file = self.folder / ("post-" + ID1 + ".json")
        file.write_text("x"*20000, encoding="utf-8")
        b = poll_browser_feed(self.config, self.store, directory=self.folder, at=self.now)
        self.assertEqual(b["rejected"], 1)
        self.assertFalse(file.exists())

    def test_notification_failure_retains_unread_alert(self):
        emit(self.folder, row(ID1, self.now - 3))
        a = poll_browser_feed(self.config, self.store, directory=self.folder,
                              at=self.now, notification=lambda *_: False)
        self.assertEqual(a["alerts"], 1)
        self.assertEqual(a["notified"], 0)
        self.assertEqual(self.store.unread_alert_count(), 1)


if __name__ == "__main__":
    unittest.main()
