"""No-network evidence triage regressions using patterns observed in real OCR."""
import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from trade_alert.config import Config
from trade_alert.event_evidence import assess_truth_evidence
from trade_alert.state import StateStore
from trade_alert.trump_filter import TrumpSignal, classify_trump_statement
from trade_alert.truth_direct import DirectPost, DirectResult, read_direct_once
from trade_alert.chrome_feed import poll_browser_feed

ACCOUNT = "107780257626128497"
T0 = datetime(2026, 10, 9, 13, tzinfo=timezone.utc).timestamp()
IMAGE_URL = "https://static-assets-1.truthsocial.com/media/test.png"

POLICY_REPORT = (
    "THE WHITE HOUSE FOR IMMEDIATE RELEASE New Report: DSA Policies "
    "Would Cost Americans Trillions over the next ten years if the "
    "policies were adopted. Double-digit interest rates and inflation."
)
HISTORIC_MILITARY = (
    "DOW Rapid Response @DOWResponse These Americans have DESTROYED "
    "Iran's Navy, Air Force and their air defense systems. "
    "Courageous and historic operations."
)


class EvidenceRulesTests(unittest.TestCase):
    def test_image_only_hypothetical_report_is_not_an_enacted_change(self):
        result = assess_truth_evidence(
            caption="Read this report.", image_text=POLICY_REPORT)
        self.assertEqual(result.event_kind, "HYPOTHETICAL")
        self.assertEqual((result.signal.priority, result.signal.score),
                         ("IGNORE", 0))
        self.assertEqual(result.verification, "INDEPENDENT_CONFIRMATION_NOT_CHECKED")
        self.assertFalse(result.corroboration_required)

    def test_immediate_primary_claim_never_waits_for_corrob(self):
        caption = "We are imposing 100 percent tariffs on China immediately."
        result = assess_truth_evidence(caption=caption, image_text=POLICY_REPORT)
        self.assertEqual(result.event_kind, "ACTION_CLAIM")
        self.assertEqual(result.signal.priority, "HIGH")
        self.assertTrue(result.corroboration_required)
        self.assertEqual(result.verification, "INDEPENDENT_CONFIRMATION_NOT_CHECKED")

    def test_retrospective_image_claim_does_not_trigger_new_high(self):
        result = assess_truth_evidence(
            caption="Our troops deserve recognition.",
            image_text=HISTORIC_MILITARY,
            signal=TrumpSignal(score=7, priority="HIGH", category="DEFENSE"),
        )
        self.assertEqual(result.event_kind, "RECAP")
        self.assertEqual(result.signal.priority, "STANDARD")
        self.assertEqual(result.signal.score, 4)
        self.assertEqual(result.signal.category, "DEFENSE")

    def test_oil_chart_stays_visible_but_not_claimed_as_new_event(self):
        result = assess_truth_evidence(
            caption="The real facts!",
            image_text="DAYS WITH CRUDE OIL ABOVE $100 2009-2017 2017-2021",
        )
        self.assertEqual((result.event_kind, result.signal.priority),
                         ("DATA_CONTEXT", "STANDARD"))

    def test_recent_production_data_keeps_standard(self):
        result = assess_truth_evidence(
            caption="", image_text="U.S. Natural Gas Production Hits Record High")
        self.assertEqual((result.event_kind, result.signal.priority),
                         ("DATA_CONTEXT", "STANDARD"))

    def test_quoted_military_praise_is_not_verified_military_action(self):
        result = assess_truth_evidence(
            caption="Thanks to our service members.",
            image_text=HISTORIC_MILITARY)
        self.assertEqual(result.event_kind, "RECAP")
        self.assertIn("third-party", result.reason)
        self.assertEqual(result.verification, "INDEPENDENT_CONFIRMATION_NOT_CHECKED")

    def test_generic_future_condition_is_not_blocked(self):
        msg = "We will impose tariffs unless the trade talks succeed."
        result = assess_truth_evidence(caption=msg)
        self.assertEqual(result.signal.priority, "HIGH")
        self.assertEqual(result.event_kind, "ACTION_CLAIM")

    def test_text_only_hypothetical_does_not_suppress_source_relay(self):
        result = assess_truth_evidence(caption=POLICY_REPORT, source="RSS")
        self.assertEqual(result.event_kind, "UNRESOLVED")
        self.assertGreaterEqual(result.signal.score, 2)
        self.assertEqual(result.provenance, "ARCHIVE_TEXT")

    def test_invalid_source_rejected(self):
        with self.assertRaises(ValueError):
            assess_truth_evidence(caption="Iran", source="UNTRUSTED")


class EvidenceIntakeTests(unittest.IsolatedAsyncioTestCase):
    async def test_direct_ocr_report_does_not_generate_policy_alert(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.db")
            store.set_meta("truth_direct_initialized", "previous")
            try:
                result = DirectResult((
                    DirectPost(
                        "117111111111111111", "Read this report.", T0,
                        "https://truthsocial.com/@realDonaldTrump/117111111111111111",
                        media_url=IMAGE_URL,
                    ),
                ), fetched_at=T0 + 5)
                with patch("trade_alert.truth_direct.extract_image_text",
                           return_value=(POLICY_REPORT, "OCR_OK")):
                    output = await read_direct_once(
                        Config(), store, fetch=lambda: result,
                        now=T0 + 8,
                        notification=lambda *args: self.fail("false policy notification"),
                    )
                self.assertEqual(output["alerted"], 0)
                self.assertEqual(output["notified"], 0)
                self.assertTrue(store.seen("TRUTH_PUBLIC:117111111111111111"))
            finally:
                store.close()

    async def test_direct_primary_policy_claim_keeps_immediate_high(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "state.db")
            store.set_meta("truth_direct_initialized", "previous")
            try:
                result = DirectResult((
                    DirectPost(
                        "117111111111111112",
                        "We are imposing 100 percent tariffs on China immediately.",
                        T0, "https://truthsocial.com/@realDonaldTrump/117111111111111112",
                        media_url=IMAGE_URL,
                    ),
                ), fetched_at=T0 + 5)
                notices = []
                with patch("trade_alert.truth_direct.extract_image_text",
                           return_value=(POLICY_REPORT, "OCR_OK")):
                    output = await read_direct_once(
                        Config(), store, fetch=lambda: result,
                        now=T0 + 8,
                        notification=lambda *args: notices.append(args) or True,
                    )
                self.assertEqual(output["alerted"], 1)
                self.assertIn("HIGH", notices[0][0])
                self.assertIn("Evidens: ACTION_CLAIM", notices[0][1])
                self.assertIn("EJ KONTROLLERAD", notices[0][1])
            finally:
                store.close()

    async def test_chrome_ocr_hypothetical_is_suppressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "inbox"
            folder.mkdir()
            store = StateStore(Path(tmp) / "state.db")
            try:
                pid = "117111111111111113"
                row = {
                    "id": pid, "visibility": "public",
                    "created_at": datetime.fromtimestamp(
                        T0, timezone.utc).isoformat(),
                    "account": {"id": ACCOUNT, "acct": "realDonaldTrump"},
                    "content": "<p>Read this report.</p>",
                    "media_attachments": [{"type": "image", "url": IMAGE_URL}],
                }
                (folder / ("post-" + pid + ".json")).write_text(json.dumps(row))
                with patch("trade_alert.chrome_feed.extract_image_text",
                           return_value=(POLICY_REPORT, "OCR_OK")):
                    output = poll_browser_feed(
                        Config(chrome_bridge_enabled=True), store,
                        directory=folder, at=T0 + 8,
                        notification=lambda *args: self.fail("false alert"),
                    )
                self.assertEqual(output["alerts"], 0)
                self.assertEqual(output["ocr_ok"], 1)
                self.assertTrue(store.seen("TRUTH_PUBLIC:" + pid))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
