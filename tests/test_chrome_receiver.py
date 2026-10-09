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
    BIND_HOST, INGEST_PATH, PAIR_PATH, start_chrome_receiver
)
from trade_alert.chrome_pairing import PairingStore
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
        self.directory = pathlib.Path(self.tmp.name) / "inbox"
        self.directory.mkdir()
        self.authdir = pathlib.Path(self.tmp.name) / "private"
        self.pairing = PairingStore(self.authdir)
        code = self.pairing.issue_code()
        self.server, self.thread = start_chrome_receiver(
            port=0, directory=self.directory, auth_directory=self.authdir
        )
        self.addCleanup(self.close_server)
        self.port = self.server.server_port
        result = self.call(
            "POST", json.dumps({"code": code}).encode(),
            url=PAIR_PATH, token=None
        )
        self.assertEqual(result[0], 200)
        self.token = json.loads(result[2])["token"]

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def call(self, method, body=b"", *, origin=ORIGIN, url=INGEST_PATH,
             bridge="1", content_type="application/json", token="default"):
        conn = http.client.HTTPConnection(BIND_HOST, self.port, timeout=3)
        headers = {"Origin": origin}
        if method == "POST":
            headers.update({
                "Content-Type": content_type,
                "X-Trade-Alert-Bridge": bridge,
            })
            if token == "default":
                token = getattr(self, "token", None)
            if token is not None:
                headers["X-Trade-Alert-Token"] = token
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

    def test_unpaired_requests_and_other_extension_are_denied(self):
        body = json.dumps(post()).encode("utf-8")
        self.assertEqual(self.call("POST", body, token=None)[0], 401)
        self.assertEqual(self.call(
            "POST", body, token="c" * 64
        )[0], 401)
        self.assertEqual(self.call(
            "POST", body, origin="chrome-extension://" + "b" * 32
        )[0], 403)
        self.assertFalse(list(self.directory.iterdir()))

    def test_one_time_pairing_replay_rejected_and_rotation_revokes_old_token(self):
        old_token = self.token
        same_code = self.pairing.issue_code()
        denied = self.call(
            "POST", json.dumps({"code": "0" * 20}).encode(),
            url=PAIR_PATH, token=None
        )
        self.assertEqual(denied[0], 403)
        approved = self.call(
            "POST", json.dumps({"code": same_code}).encode(),
            url=PAIR_PATH, token=None
        )
        self.assertEqual(approved[0], 200)
        new_token = json.loads(approved[2])["token"]
        self.assertNotEqual(new_token, old_token)
        replay = self.call(
            "POST", json.dumps({"code": same_code}).encode(),
            url=PAIR_PATH, token=None
        )
        self.assertEqual(replay[0], 403)
        self.assertEqual(self.call(
            "POST", json.dumps(post()).encode(), token=old_token
        )[0], 401)
        self.assertEqual(self.call(
            "POST", json.dumps(post()).encode(), token=new_token
        )[0], 200)

    def test_pair_rate_limit_and_http_rejection(self):
        for _ in range(4):
            self.assertEqual(self.call(
                "POST", b'{"code":"00000000000000000000"}',
                url=PAIR_PATH, token=None
            )[0], 403)
        self.assertEqual(self.call(
            "POST", b'{"code":"00000000000000000000"}',
            url=PAIR_PATH, token=None
        )[0], 429)
        # Existing authorized posts still work when pair attempts are blocked.
        self.assertEqual(self.call(
            "POST", json.dumps(post()).encode()
        )[0], 200)

    def test_reject_many_unauthorized_requests(self):
        body = json.dumps(post()).encode()
        for _ in range(12):
            self.assertEqual(self.call("POST", body, token=None)[0], 401)
        self.assertEqual(self.call("POST", body, token=None)[0], 429)
        self.assertEqual(self.call("POST", body)[0], 200)

    def test_binds_loopback_only(self):
        self.assertEqual(self.server.server_address[0], "127.0.0.1")


if __name__ == "__main__":
    unittest.main()
