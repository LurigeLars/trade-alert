import unittest

from trade_alert.config import Config
from trade_alert.state import AlertRecord
from trade_alert.tray import (
    format_alert_history,
    make_status_icon,
    monitoring_summary,
    resolve_theme,
    theme_palette,
)


class TrayTests(unittest.TestCase):
    def test_status_icons_are_runtime_generated_rgba_images(self):
        for health in ("ok", "waiting", "error", "paused"):
            image = make_status_icon(health)
            self.assertEqual((64, 64), image.size)
            self.assertEqual("RGBA", image.mode)

    def test_unread_alert_adds_badge(self):
        normal = make_status_icon("ok", unread=0)
        unread = make_status_icon("ok", unread=1)
        self.assertNotEqual(normal.getpixel((50, 10)), unread.getpixel((50, 10)))

    def test_monitoring_summary_exposes_effective_configuration(self):
        config = Config(
            profile_name="Oil / Brent",
            official_symbols=("ICEEUR:BRN1!",),
            dtv_watchlist_id=None,
            poll_seconds=20,
            official_poll_seconds=30,
            notification_min_score=2,
        )
        summary = monitoring_summary(config)
        self.assertIn("Oil / Brent", summary)
        self.assertIn("ICEEUR:BRN1!", summary)
        self.assertIn("INAKTIV", summary)
        self.assertIn("var 20 s", summary)
        self.assertIn("var 30 s", summary)
        self.assertIn("relevanspoäng ≥ 2", summary)
        self.assertIn("ingen LLM", summary)

    def test_theme_resolution_defaults_system_to_detected_windows_mode(self):
        self.assertEqual("dark", resolve_theme("system", system_dark=True))
        self.assertEqual("light", resolve_theme("system", system_dark=False))
        self.assertEqual("dark", resolve_theme("dark", system_dark=False))
        self.assertEqual("light", resolve_theme("light", system_dark=True))

    def test_theme_palettes_have_accessible_selection_contrast(self):
        for theme in ("light", "dark"):
            palette = theme_palette(theme)
            self.assertIn("window", palette)
            self.assertIn("surface", palette)
            self.assertIn("text", palette)
            self.assertIn("selection", palette)
            self.assertNotEqual(palette["surface"], palette["text"])
            self.assertNotEqual(palette["selection"], palette["selection_text"])

    def test_alert_history_keeps_full_headline_and_link(self):
        record = AlertRecord(
            item_key="a",
            created_at=100.0,
            published=90.0,
            source="TV:ICEEUR:BRN1!",
            provider="Reuters",
            headline="A complete oil market headline",
            body="body",
            score=4,
            link="https://example.test/story",
            unread=True,
        )
        text = format_alert_history([record], 1)
        self.assertIn("OLÄST", text)
        self.assertIn("A complete oil market headline", text)
        self.assertIn("Reuters", text)
        self.assertIn("relevans 4", text)
        self.assertIn("https://example.test/story", text)


if __name__ == "__main__":
    unittest.main()
