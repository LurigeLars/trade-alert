"""Offline localhost receiver tests: loopback, origin and post validation."""
import http.client
import json
import pathlib
import tempfile
import time
import unittest
from datetime import datetime, timezone

from trade_alert.chrome_feed import poll_browser_feed
from trade_alert.chrome_receiver import (
    BIND_HOST, INGEST_PATH, start_chrome_receiver
)
from trade_alert.config import Config
from trade_alert.state import StateStore

ORIGIN = "chrome-extension://" + "a" * 32
POST_ID = "117406186276133332"
ACCOUNT = "107780257626128497"


def post(account=ACCOUNT):
    return {
        "id": POST_ID,
        "created_at": datetime.fromtimestamp(
            time.time() - 3, timezone.utc
        ).isoformat().replace("+00:00", "Z"),
        "visibility": "public",
        "account": {"id": account, "acct": "realDonaldTrump",
                    "username": "realDonaldTrump"},
        "content": "<p>We are deploying our Navy to Cuba.</p>",
        "media_attachments": [],
    }


class LoopbackReceiverTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = pathlib.Path(self.tmp.name)
        self.server, self.thread = start_chrome_receiver(
            port=0, directory=self.directory
        )
        self.addCleanup(self.close_server)
        self.port = self.server.server_port

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def call(self, method, body=b"", *, origin=ORIGIN, url=INGEST_PATH,
             bridge="1", content_type="application/json"):
        conn = http.client.HTTPConnection(BIND_HOST, self.port, timeout=3)
        headers = {"Origin": origin}
        if method == "POST":
            headers.update({
                "Content-Type": content_type,
                "X-Trade-Alert-Bridge": bridge,
            })
        conn.request(method, url, body, headers)
        response = conn.getresponse()
        data = response.read()
        result = (response.status, dict(response.getheaders()), data)
        conn.close()
        return result

    def test_verified_post_queued_without_browser_download_and_consumed(self):
        data = json.dumps(post()).encode("utf-8")
        status, headers, body = self.call("POST", data)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body), {"status":"QUEUED","id":POST_ID})
        self.assertEqual(headers["Access-Control-Allow-Origin"], ORIGIN)
        self.assertEqual(
            [p.name for p in self.directory.iterdir()],
            ["post-" + POST_ID + ".json"],
        )
        state = StateStore(self.directory / "state.db")
        try:
            notified = []
            result = poll_browser_feed(
                Config(chrome_bridge_enabled=True),
                state, directory=self.directory,
                notification=lambda *args: notified.append(args) or True,
            )
            self.assertEqual(result["alerts"], 1)
            self.assertEqual(result["notified"], 1)
            self.assertEqual(len(notified), 1)
            self.assertIn("HIGH", notified[0][0])
            self.assertFalse((self.directory /
                              ("post-" + POST_ID + ".json")).exists())
        finally:
            state.close()

    def test_reject_untrusted_origin_or_missing_bridge_header(self):
        data = json.dumps(post()).encode("utf-8")
        for kwargs in (
            {"origin":"https://truthsocial.com"},
            {"origin":"https://attacker.example"},
            {"origin":"chrome-extension://invalid"},
            {"bridge":"0"},
            {"content_type":"text/plain"},
            {"url":"/not-approved"},
        ):
            with self.subTest(kwargs=kwargs):
                status, _, _ = self.call("POST", data, **kwargs)
                self.assertEqual(status, 403)
        self.assertEqual(list(self.directory.iterdir()), [])

    def test_reject_identity_failure_and_oversized_request(self):
        bad = json.dumps(post(account="wrong")).encode("utf-8")
        self.assertEqual(self.call("POST", bad)[0], 400)
        self.assertEqual(self.call("POST", b"x" * 18000)[0], 413)
        self.assertFalse(list(self.directory.glob("post-*.json")))

    def test_cors_preflight_only_for_chrome_extension_origin(self):
        status, headers, data = self.call("OPTIONS")
        self.assertEqual(status, 204)
        self.assertEqual(data, b"")
        self.assertEqual(headers["Access-Control-Allow-Origin"], ORIGIN)
        self.assertIn("POST", headers["Access-Control-Allow-Methods"])
        denied = self.call("OPTIONS", origin="https://truthsocial.com")
        self.assertEqual(denied[0], 403)

    def test_binds_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
