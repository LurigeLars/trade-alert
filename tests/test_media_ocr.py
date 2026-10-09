"""Local public-media OCR constraints and deterministic no-network tests."""
import io
import subprocess
import unittest
from unittest.mock import patch
from PIL import Image

from trade_alert.media_ocr import (
    OCRFetchFailed, OCRUnavailable, image_url_from_post, is_approved_image_url,
    recognize_image_bytes, extract_image_text, MAX_IMAGE_BYTES,
)

CDN = "https://static-assets-1.truthsocial.com/media_attachments/test.png"


def picture() -> bytes:
    image = Image.new("RGB", (240, 96), color="white")
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


class ImageOCRTests(unittest.TestCase):
    def test_only_public_static_image_hosts(self):
        self.assertTrue(is_approved_image_url(CDN))
        self.assertTrue(is_approved_image_url(
            "https://static-assets-2.truthsocial.com/media/original/a.jpeg"))
        for value in (
            "http://static-assets-1.truthsocial.com/a.png",
            "https://static-assets-1.truthsocial.com.evil.test/a.png",
            "https://127.0.0.1/a.png", "file:///C:/secret.txt",
            "https://localhost/a.png", "https://static-assets-1.truthsocial.com:81/a.png",
            "https://evil.test@static-assets-1.truthsocial.com/a.png",
            "https://static-assets-1.truthsocial.com/a.png#fragment",
            "data:image/png;base64,SGVsbG8=", "", None
        ):
            with self.subTest(value=value):
                self.assertFalse(is_approved_image_url(value))

    def test_image_url_must_be_explicitly_image_type(self):
        self.assertEqual(image_url_from_post({
            "media_attachments": [{"type":"image","url":CDN}]
        }), CDN)
        self.assertIsNone(image_url_from_post({
            "media_attachments": [{"type":"video","url":CDN}]
        }))
        self.assertIsNone(image_url_from_post({
            "media_attachments": [{"type":"image","url":"https://example.com/a.png"}]
        }))
        self.assertEqual(image_url_from_post({
            "media_attachments": [
                {"type":"image","url":"https://example.com/a.png",
                 "preview_url":CDN}
            ]
        }), CDN)

    def test_local_tesseract_output_reaches_energy_classifier(self):
        fake = subprocess.CompletedProcess(
            args=["tesseract"], returncode=0,
            stdout=b"DAYS WITH CRUDE OIL ABOVE $100\n2009 - 2017\n",
        )
        with patch("trade_alert.media_ocr.subprocess.run", return_value=fake) as run:
            extracted = recognize_image_bytes(picture(), executable="tesseract")
        self.assertIn("CRUDE OIL", extracted)
        from trade_alert.trump_filter import classify_trump_statement
        classification = classify_trump_statement(
            "The Dumocrats are Scammers. These are the real facts! " + extracted
        )
        self.assertEqual(classification.category, "ENERGY")
        self.assertGreaterEqual(classification.score, 4)
        self.assertEqual(classification.priority, "STANDARD")
        args, kwargs = run.call_args
        self.assertEqual(args[0][0], "tesseract")
        self.assertEqual(kwargs["timeout"], 6)
        self.assertEqual(kwargs["stderr"], subprocess.DEVNULL)

    def test_missing_executable_is_explicitly_unavailable(self):
        with patch("trade_alert.media_ocr.tesseract_path", return_value=None):
            self.assertEqual(extract_image_text({
                "media_attachments":[{"type":"image","url":CDN}]
            }), ("", "OCR_UNAVAILABLE"))
        with self.assertRaises(OCRUnavailable):
            recognize_image_bytes(picture(), executable="")

    def test_oversized_or_invalid_payload_fails_closed(self):
        for data in (b"not an image", b"X" * (MAX_IMAGE_BYTES + 1)):
            with self.subTest(size=len(data)):
                with self.assertRaises(OCRFetchFailed):
                    recognize_image_bytes(data, executable="tesseract")

    def test_fetched_image_never_requires_cloud_ocr(self):
        with patch("trade_alert.media_ocr.tesseract_path", return_value="tesseract"):
            with patch("trade_alert.media_ocr._fetch_image", return_value=picture()) as get:
                with patch("trade_alert.media_ocr.recognize_image_bytes",
                           return_value="CRUDE OIL ABOVE 100") as ocr:
                    text, status = extract_image_text({
                        "media_attachments":[{"type":"image","url":CDN}]
                    })
        self.assertEqual((text, status), ("CRUDE OIL ABOVE 100", "OCR_OK"))
        get.assert_called_once_with(CDN)
        ocr.assert_called_once()


if __name__ == "__main__":
    unittest.main()
