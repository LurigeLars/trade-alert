import pathlib
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from trade_alert.config import Config
from trade_alert.state import AlertRecord, StateStore
from trade_alert.tray import (
    format_alert_history,
    make_status_icon,
    monitoring_summary,
    normalize_news_link,
    resolve_theme,
    theme_palette,
    TrayController,
)


class TrayTests(unittest.TestCase):
    def test_latest_alerts_is_the_only_default_tray_action(self):
        controller = TrayController.__new__(TrayController)
        controller.config = Config()
        controller.pause_event = threading.Event()
        controller._unread_count = 0

        menu = controller._build_menu()
        defaults = [
            item for item in menu.items
            if getattr(item, "default", False)
        ]

        self.assertEqual(1, len(defaults))
        self.assertEqual("Senaste alerts", defaults[0].text)

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
        self.assertIn("PRIMÄR", summary)
        self.assertIn("auto-upptäcker", summary)
        self.assertIn("var 20 s", summary)
        self.assertIn("max 200 headlines", summary)
        self.assertIn("replay-overlap: 3600 s", summary)
        self.assertIn("var 30 s", summary)
        self.assertIn("targeted corroboration", summary)
        self.assertIn("routing evidence", summary)
        self.assertIn("relevanspoäng ≥ 2", summary)
        self.assertIn("ingen LLM", summary)

    def test_monitoring_summary_shows_locally_auto_pinned_watchlist_name(self):
        summary = monitoring_summary(
            Config(),
            resolved_watchlist_name="Watchlist",
            auto_pinned_watchlist=True,
        )
        self.assertIn("auto-pinnad lokalt", summary)
        self.assertIn("Watchlist", summary)

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

    def test_news_link_normalization_accepts_https_and_tradingview_relative_paths(self):
        self.assertEqual(
            "https://example.test/story",
            normalize_news_link("https://example.test/story"),
        )
        self.assertEqual(
            "https://www.tradingview.com/news/reuters.com,2026:newsml_TEST/",
            normalize_news_link("/news/reuters.com,2026:newsml_TEST/"),
        )

    def test_news_link_normalization_rejects_untrusted_schemes(self):
        self.assertIsNone(normalize_news_link("javascript:alert(1)"))
        self.assertIsNone(normalize_news_link("file:///C:/secret.txt"))
        self.assertIsNone(normalize_news_link("//example.test/story"))
        self.assertIsNone(normalize_news_link(""))

    def test_legacy_dtv_alert_does_not_claim_later_observation_as_first_seen(self):
        record = AlertRecord(
            item_key="legacy",
            created_at=120.0,
            published=90.0,
            dtv_first_seen=130.0,
            source="DTV_NEWS_FLOW",
            provider="Trading Economics",
            headline="Oil Prices Ease on Trump remarks about Iran",
            body="body",
            score=5,
            link=None,
            unread=False,
        )
        text = format_alert_history([record], 0)
        self.assertIn("DTV först sedd: ≤", text)
        self.assertIn("exakt tid ej mätt", text)
        self.assertNotIn("1970-01-01 01:02:10", text)

    def test_alert_history_keeps_full_headline_and_link(self):
        record = AlertRecord(
            item_key="a",
            created_at=100.0,
            published=90.0,
            dtv_first_seen=95.0,
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
        self.assertIn("DTV först sedd:", text)
        self.assertIn("Alert registrerad:", text)
        self.assertIn("https://example.test/story", text)


    def test_history_expands_to_30_and_marks_only_displayed_alerts_read(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "state.db"
            store = StateStore(path)
            try:
                for number in range(30):
                    store.record_alert(
                        item_key=f"story-{number}",
                        source="DTV_NEWS_FLOW",
                        headline=f"Headline {number}",
                        body="body",
                        score=3,
                        at=100.0 + number,
                    )
            finally:
                store.close()

            controller = TrayController.__new__(TrayController)
            controller.config = Config()
            controller._health = "ok"
            controller._unread_count = 30
            controller._refresh_tray = Mock()

            with (
                patch("trade_alert.tray.StateStore", side_effect=lambda: StateStore(path)),
                patch("trade_alert.tray._show_text_window") as window,
            ):
                controller._show_alert_history(None, None)
                self.assertEqual(20, controller._unread_count)
                text = window.call_args.args[1]
                self.assertIn("Olästa före öppning: 30", text)
                self.assertIn("Senaste 10 alerts:", text)
                self.assertIn("Headline 29", text)
                self.assertNotIn("Headline 0", text)
                self.assertEqual("Visa alla 30", window.call_args.kwargs["show_all_label"])

                expanded_text = window.call_args.kwargs["on_show_all"]()
                self.assertIn("Senaste 30 alerts:", expanded_text)
                self.assertIn("Headline 0", expanded_text)
                self.assertEqual(0, controller._unread_count)
                self.assertEqual(2, controller._refresh_tray.call_count)

            reopened = StateStore(path)
            try:
                self.assertEqual(0, reopened.unread_alert_count())
            finally:
                reopened.close()

    def test_history_with_10_alerts_has_no_expand_button(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "state.db"
            store = StateStore(path)
            try:
                for number in range(10):
                    store.record_alert(
                        item_key=f"story-{number}",
                        source="DTV_NEWS_FLOW",
                        headline=f"Headline {number}",
                        body="body",
                        score=3,
                        at=100.0 + number,
                    )
            finally:
                store.close()

            controller = TrayController.__new__(TrayController)
            controller.config = Config()
            controller._health = "ok"
            controller._unread_count = 10
            controller._refresh_tray = Mock()

            with (
                patch("trade_alert.tray.StateStore", side_effect=lambda: StateStore(path)),
                patch("trade_alert.tray._show_text_window") as window,
            ):
                controller._show_alert_history(None, None)
                self.assertEqual(0, controller._unread_count)
                self.assertIsNone(window.call_args.kwargs["show_all_label"])
                self.assertIsNone(window.call_args.kwargs["on_show_all"])


if __name__ == "__main__":
    unittest.main()
