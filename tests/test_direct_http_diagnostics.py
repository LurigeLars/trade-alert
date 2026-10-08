"""Test bounded HTTP-denial evidence and no stateful side effects."""
import io
import json
import sys
import unittest
import urllib.error
from email.message import Message
from unittest.mock import patch
from trade_alert.truth_direct import DirectResult

from trade_alert.truth_direct import DirectUnavailable, fetch_public_statuses


def simulated_denial(code=403, headers=None, body=b"Forbidden"):
    values = Message()
    for name, value in (headers or {}).items():
        values[name] = value
    return urllib.error.HTTPError(
        "https://truthsocial.com/api/v1/accounts/EXAMPLE/statuses",
        code, "denied", values, io.BytesIO(body),
    )


class DirectHttpDiagnosticTests(unittest.TestCase):
    def _probe(self, http_error):
        class Opener:
            calls = 0
            def open(self, request, timeout):
                self.calls += 1
                raise http_error
        opener = Opener()
        with patch("trade_alert.truth_direct.urllib.request.build_opener",
                   return_value=opener):
            with self.assertRaises(DirectUnavailable) as caught:
                fetch_public_statuses()
        self.assertEqual(opener.calls, 1)
        return caught.exception

    def test_cloudflare_challenge_evidence(self):
        exc = self._probe(simulated_denial(
            headers={"Server": "cloudflare", "CF-Ray": "abc123-ARN",
                     "CF-Mitigated": "challenge", "Content-Type": "text/html"},
            body=b"<html>Secret session=a.private.token</html>"))
        d = exc.diagnostic
        self.assertTrue(exc.blocked)
        self.assertEqual(d["http_status"], 403)
        self.assertEqual(d["classification"], "CLOUDFLARE_CHALLENGE")
        self.assertEqual(d["server"], "cloudflare")
        self.assertEqual(d["content_type"], "text/html")
        self.assertEqual(d["cf_ray"], "abc123-ARN")
        self.assertEqual(d["cf_mitigated"], "challenge")
        self.assertGreaterEqual(d["elapsed_ms"], 0)
        self.assertNotIn("Secret", str(d))
        self.assertNotIn("a.private.token", str(d))

    def test_cloudflare_ray_does_not_prove_bottspärr(self):
        exc = self._probe(simulated_denial(
            headers={"CF-Ray": "deadbeef-ARN"}, body=b"access denied"))
        self.assertEqual(
            exc.diagnostic["classification"],
            "CLOUDFLARE_PRESENT_CAUSE_UNDETERMINED",
        )

    def test_cloudflare_1020_and_geographic_clues(self):
        block = self._probe(simulated_denial(
            body=b"<p>Cloudflare error code: 1020</p>"))
        self.assertEqual(block.diagnostic["classification"], "CLOUDFLARE_WAF_1020")
        geo = self._probe(simulated_denial(
            body=b"Sorry, this service is not available in your country"))
        self.assertEqual(geo.diagnostic["classification"], "POSSIBLE_GEOGRAPHIC_RESTRICTION")

    def test_possible_login_requirement(self):
        e = self._probe(simulated_denial(
            headers={"Content-Type": "application/json"},
            body=b'{"message":"Authentication required","secret":"do not print"}'))
        self.assertEqual(
            e.diagnostic["classification"],
            "POSSIBLE_AUTHENTICATION_REQUIREMENT",
        )
        self.assertNotIn("do not print", str(e.diagnostic))

    def test_body_is_bounded_and_headers_sanitized(self):
        e = self._probe(simulated_denial(
            headers={"Server": "Example\r\nSet-Cookie: secret=abc",
                     "CF-Ray": "bad!@#$chars"},
            body=b"random " * 4000 + b"do not print"))
        d = e.diagnostic
        self.assertEqual(d["inspected_body_bytes"], 4096)
        self.assertNotIn("Set-Cookie:", str(d))
        self.assertNotIn("secret=abc", str(d))
        self.assertNotIn("do not print", str(d))
        self.assertLessEqual(len(d["server"]), 100)

    def test_429_is_blocked_without_retry(self):
        e = self._probe(simulated_denial(code=429))
        self.assertTrue(e.blocked)
        self.assertEqual(e.diagnostic["http_status"], 429)


    def test_diagnostic_cli_is_read_only_and_does_not_log_body(self):
        from trade_alert.app import main
        blocked = DirectUnavailable(
            "HTTP 403 from Truth Social public endpoint",
            blocked=True,
            diagnostic={"http_status": 403, "classification": "CLOUDFLARE_CHALLENGE"},
        )
        output = io.StringIO()
        with patch.object(sys, "argv", ["trade-alert", "--diagnose-direct"]), \
             patch("trade_alert.app.configure_windows_app_identity"), \
             patch("trade_alert.app.configure_windows_dpi_awareness"), \
             patch("trade_alert.app._setup_logging"), \
             patch("trade_alert.app.fetch_public_statuses", side_effect=blocked), \
             patch("trade_alert.app.Config.load"), \
             patch("trade_alert.app.StateStore", side_effect=AssertionError("must not access store")), \
             patch("sys.stdout", output):
            main()
        report = json.loads(output.getvalue())
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["http"]["classification"], "CLOUDFLARE_CHALLENGE")
        self.assertNotIn("password", output.getvalue())


if __name__ == "__main__":
    unittest.main()
