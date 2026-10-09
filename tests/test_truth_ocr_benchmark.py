"""No-network benchmark regressions for the public-image OCR sample."""
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.benchmark_truth_ocr import benchmark

URL1 = "https://static-assets-1.truthsocial.com/test/a.png"
URL2 = "https://static-assets-1.truthsocial.com/test/b.png"
URL3 = "https://static-assets-1.truthsocial.com/test/c.png"


def item(post, url, eligible=True):
    return {"status_id": str(post), "media_id": str(post),
            "url": url, "scanner_eligible": eligible}


class BenchmarkTests(unittest.TestCase):
    @staticmethod
    def signal(text):
        return SimpleNamespace(priority="STANDARD" if "OIL" in text else "IGNORE",
                               category="ENERGY" if "OIL" in text else "OTHER",
                               score=2 if "OIL" in text else 0)

    def test_first_image_only_and_image_only_classification(self):
        seen = []
        def fetch(url):
            seen.append(url)
            return url.encode()
        result = benchmark([item(1, URL1), item(2, URL2, False),
                            item(3, URL3)], limit=2,
                           fetch=fetch, recognize=lambda _: "CRUDE OIL",
                           classify=self.signal, sleep=lambda _: None)
        self.assertEqual(seen, [URL1, URL3])
        self.assertEqual(result["processed_unique_images"], 2)
        self.assertEqual(result["priority_counts"], {"STANDARD": 2})
        self.assertEqual(result["stop_reason"], "EXHAUSTED")

    def test_identical_image_bytes_do_not_count_twice(self):
        def fetch(url):
            return b"same" if url != URL3 else b"different"
        report = benchmark([item(1, URL1), item(2, URL2), item(3, URL3)],
                           limit=2, fetch=fetch, recognize=lambda _: "hello",
                           classify=self.signal, sleep=lambda _: None)
        self.assertEqual(report["processed_unique_images"], 2)
        self.assertEqual(report["status_counts"]["DUPLICATE_IMAGE"], 1)

    def test_three_fetch_failures_open_circuit(self):
        from trade_alert.media_ocr import OCRFetchFailed
        calls = []
        def blocked(url):
            calls.append(url)
            raise OCRFetchFailed("HTTP 403")
        report = benchmark([item(1, URL1), item(2, URL2),
                            item(3, URL3), item(4, URL1)],
                           fetch=blocked, sleep=lambda _: None)
        self.assertEqual(len(calls), 3)
        self.assertEqual(report["stop_reason"], "FETCH_FAILURE_CIRCUIT_OPEN")

    def test_unapproved_url_is_never_fetched(self):
        report = benchmark([item(1, "https://example.org/f.png")],
                           fetch=lambda _: self.fail("network attempted"),
                           sleep=lambda _: None)
        self.assertEqual(report["status_counts"], {"INVALID_SOURCE": 1})


if __name__ == "__main__":
    unittest.main()
