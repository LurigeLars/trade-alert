"""Read-only, no-network OCR evidence replay tests."""
import unittest

from scripts.replay_truth_evidence import replay


class ReplayTruthEvidenceTests(unittest.TestCase):
    def test_replay_text_only_categorizes_hypothetical_without_alert(self):
        report = {
            "results": [
                {
                    "status": "OCR_OK", "status_id": "11111111111",
                    "ocr_text": (
                        "New Report: DSA Policies Would Cost Americans Trillions "
                        "if the policies were adopted; interest rates would skyrocket"
                    ),
                    "priority": "STANDARD", "category": "RATES", "score": 4,
                },
                {
                    "status": "OCR_OK", "status_id": "22222222222",
                    "ocr_text": "DAYS WITH CRUDE OIL ABOVE $100",
                    "priority": "STANDARD", "category": "ENERGY", "score": 4,
                },
                {"status": "DUPLICATE_IMAGE", "status_id": "33333333333"},
            ]
        }
        result = replay(report)
        self.assertEqual(result["images"], 2)
        self.assertEqual(result["after"], {"IGNORE": 1, "STANDARD": 1})
        self.assertEqual(len(result["changes"]), 1)
        self.assertEqual(result["changes"][0]["event_kind"], "HYPOTHETICAL")
        self.assertTrue(result["ocr_only"])

    def test_malformed_report_rejected(self):
        with self.assertRaises(ValueError):
            replay({"results": "wrong"})
        with self.assertRaises(ValueError):
            replay({"results": [{"status": "OCR_OK"}]})


if __name__ == "__main__":
    unittest.main()
