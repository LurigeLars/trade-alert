import pathlib
from datetime import datetime
from dataclasses import replace
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from trade_alert.config import Config
from trade_alert.state import AlertRecord, StateStore
from trade_alert.tray import (
    _layout_information_panes,
    _local_timestamp,
    format_alert_history,
    make_status_icon,
    make_window_icon,
    monitoring_summary,
    normalize_news_link,
    resolve_theme,
    save_static_shortcut_icon,
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

    def test_info_window_reserves_fixed_footer_below_expanding_content(self):
        """Regression: on Windows DPI scaling the old pack layout hid every button."""
        events = []

        class Pane:
            def __init__(self, name):
                self.name = name

            def grid(self, **kwargs):
                events.append((self.name, "grid", kwargs))

            def grid_rowconfigure(self, row, **kwargs):
                events.append((self.name, "grid_rowconfigure", row, kwargs))

            def grid_columnconfigure(self, column, **kwargs):
                events.append((self.name, "grid_columnconfigure", column, kwargs))

        outer, content, footer = Pane("outer"), Pane("text"), Pane("footer")
        _layout_information_panes(outer, content, footer)

        self.assertEqual(
            [
                ("outer", "grid_rowconfigure", 0, {"weight": 1}),
                ("outer", "grid_rowconfigure", 1, {"weight": 0}),
                ("outer", "grid_columnconfigure", 0, {"weight": 1}),
                ("text", "grid", {"row": 0, "column": 0, "sticky": "nsew"}),
                ("footer", "grid", {"row": 1, "column": 0, "sticky": "ew"}),
            ],
            events,
        )

    def test_status_icons_are_runtime_generated_rgba_images(self):
        for health in ("ok", "waiting", "error", "paused"):
            image = make_status_icon(health)
            self.assertEqual((64, 64), image.size)
            self.assertEqual("RGBA", image.mode)

    def test_static_shortcut_ico_reuses_tray_art_without_unread_badge(self):
        from PIL import Image

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "icons" / "Trade Alert.ico"
            generated = save_static_shortcut_icon(path)
            self.assertEqual(path, generated)
            self.assertTrue(path.is_file())

            with Image.open(path) as ico:
                self.assertEqual("ICO", ico.format)
                self.assertEqual((64, 64), ico.size)
                self.assertIn((16, 16), ico.info["sizes"])
                self.assertIn((32, 32), ico.info["sizes"])
                self.assertIn((64, 64), ico.info["sizes"])
                # The green healthy motif is static; unread badges belong only
                # to the live tray icon, not the pinned taskbar shortcut.
                self.assertEqual(
                    make_status_icon("ok", unread=0).getpixel((51, 11)),
                    ico.convert("RGBA").getpixel((51, 11)),
                )

    def test_window_icon_is_static_app_branding_not_stale_unread_status(self):
        brand = make_window_icon()
        self.assertEqual(
            brand.tobytes(), make_status_icon("ok", unread=0).tobytes()
        )
        for transient_health in ("waiting", "error", "paused"):
            self.assertNotEqual(
                brand.tobytes(),
                make_status_icon(transient_health, unread=7).tobytes(),
            )

    def test_monitoring_dialog_uses_static_icon_even_when_tray_is_degraded(self):
        controller = TrayController.__new__(TrayController)
        controller.config = Config()
        controller._health = "waiting"
        controller._unread_count = 7
        with (
            patch("trade_alert.tray.StateStore"),
            patch("trade_alert.tray._show_text_window") as window,
        ):
            controller._show_monitoring(None, None)
        self.assertEqual(
            window.call_args.args[3].tobytes(),
            make_window_icon().tobytes(),
        )

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

    def test_history_only_shows_publication_timestamp(self):
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
        with patch("trade_alert.tray._local_timestamp", return_value="publication-time") as timestamp:
            text, links = format_alert_history([record], 0)
        timestamp.assert_called_once_with(90.0)
        self.assertNotIn("Publicerad:", text)
        self.assertNotIn("DTV först sedd", text)
        self.assertNotIn("registrerad", text)
        self.assertEqual(1, text.count("publication-time"))

    def test_alert_history_is_two_lines_with_headline_link_metadata(self):
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
        with patch("trade_alert.tray._local_timestamp", return_value="22:37 12/10"):
            text, links = format_alert_history([record], 1)
        self.assertIn("OLÄST", text)
        self.assertIn("A complete oil market headline", text)
        self.assertIn("Reuters", text)
        self.assertNotIn("relevans", text)
        self.assertNotIn("Publicerad:", text)
        self.assertNotIn("DTV först sedd:", text)
        self.assertNotIn("registrerad", text)
        self.assertNotIn("https://example.test/story", text)
        self.assertNotIn("Källa:", text)
        self.assertNotIn("Länk:", text)
        self.assertEqual("[OLÄST] 22:37 12/10\nReuters · A complete oil market headline",
                         text.split("Senaste 1 alerts:\n\n", 1)[1])
        self.assertEqual([(6, "Reuters · ", "https://example.test/story")], links)

    def test_publication_time_is_local_and_compact_or_unknown(self):
        local = datetime(2026, 10, 12, 22, 37, 43)
        self.assertEqual("22:37 12/10", _local_timestamp(local.timestamp()))
        for value in (None, float("inf"), float("nan")):
            self.assertEqual("okänd", _local_timestamp(value))

    def test_duplicate_headlines_have_distinct_links_and_invalid_urls_stay_plain(self):
        record = AlertRecord(item_key="one", created_at=0, published=None, dtv_first_seen=None,
                             source="DTV_NEWS_FLOW", provider="Reuters", headline="Same headline",
                             body="body", score=2, link="/news/story-one/", unread=True)
        records = [record, replace(record, item_key="two", link="/news/story-two/"),
                   replace(record, item_key="three", link="javascript:bad"),
                   replace(record, item_key="four", provider=None, link=None, unread=False)]
        text, links = format_alert_history(records, 4)
        self.assertEqual([(6, "Reuters · ", "https://www.tradingview.com/news/story-one/"),
                          (9, "Reuters · ", "https://www.tradingview.com/news/story-two/")], links)
        self.assertIn("[läst] okänd\nDTV_NEWS_FLOW · Same headline", text)

    def test_provider_and_headline_newlines_do_not_change_link_target_rows(self):
        record = AlertRecord(item_key="one", created_at=0, published=None, dtv_first_seen=None,
                             source="TEST", provider="Reuters\nWorld", headline="Oil\r\nmarket update",
                             body="body", score=2, link="https://example.test/article", unread=True)
        text, links = format_alert_history([record, replace(record, item_key="two")], 2)
        self.assertEqual("Reuters World · Oil market update", text.splitlines()[5])
        self.assertEqual([6, 9], [line for line, _prefix, _url in links])

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
                self.assertEqual(30, controller._unread_count)
                window.call_args.kwargs["on_shown"]()
                self.assertEqual(20, controller._unread_count)
                text = window.call_args.args[1]
                self.assertIn("Olästa före öppning: 30", text)
                self.assertIn("Senaste 10 alerts:", text)
                self.assertIn("Headline 29", text)
                self.assertNotIn("Headline 0", text)
                self.assertEqual("Visa alla 30", window.call_args.kwargs["show_all_label"])
                self.assertEqual(
                    window.call_args.args[3].tobytes(),
                    make_window_icon().tobytes(),
                )

                expanded_text, expanded_links = window.call_args.kwargs["on_show_all"]()
                self.assertEqual(20, controller._unread_count)
                window.call_args.kwargs["on_shown"]()
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
                self.assertEqual(10, controller._unread_count)
                window.call_args.kwargs["on_shown"]()
                self.assertEqual(0, controller._unread_count)
                self.assertIsNone(window.call_args.kwargs["show_all_label"])
                self.assertIsNone(window.call_args.kwargs["on_show_all"])


if __name__ == "__main__":
    unittest.main()
