import json
import os
import pathlib
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch

from trade_alert.app import run_once
from trade_alert.config import Config, ConfigReloader, Watch
from trade_alert.news import Headline, matching_watches
from trade_alert.state import StateStore
from trade_alert.tray import apply_settings, monitoring_summary, parse_terms

MSFT = Watch(name="Microsoft", keywords=("Microsoft", "MSFT"), symbols=("NASDAQ:MSFT",))


def headline(title, *, item_id="x", symbols=(), published=None):
    return Headline(source="DTV_NEWS_FLOW", item_id=item_id, title=title,
                    published=time.time() - 5 if published is None else published,
                    provider="Reuters", related_symbols=symbols)


class WatchConfigTests(unittest.TestCase):
    def test_watches_round_trip_through_config_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "config.json"
            Config(watches=(MSFT,), oil_watch_enabled=False).save(path)
            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(["Microsoft", "MSFT"], raw["watches"][0]["keywords"])
            loaded = Config.load(path)
            self.assertEqual((MSFT,), loaded.watches)
            self.assertFalse(loaded.oil_watch_enabled)

    def test_invalid_watches_are_refused(self):
        bad = [
            Watch(name="", keywords=("a",)),
            Watch(name="Tom"),
            Watch(name="Sym", symbols=("MSFT",)),
            Watch(name="Sym", symbols=("NASDAQ: MSFT",)),
        ]
        for watch in bad:
            with self.subTest(watch=watch), self.assertRaises(ValueError):
                Config(watches=(watch,)).validate()
        with self.assertRaises(ValueError):
            Config(watches=(MSFT, Watch(name="microsoft", keywords=("x",)))).validate()

    def test_unknown_watch_field_is_refused_on_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "config.json"
            path.write_text(json.dumps({"watches": [{"name": "A", "keywords": ["a"], "typo": 1}]}),
                            encoding="utf-8")
            with self.assertRaises(ValueError):
                Config.load(path)

    def test_reloader_applies_disk_edit_to_shared_instance_and_keeps_last_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "config.json"
            shared = Config()
            shared.save(path)
            reloader = ConfigReloader(shared, path)
            self.assertFalse(reloader.poll())

            Config(watches=(MSFT,), truth_direct_enabled=False).save(path)
            os.utime(path, (time.time() + 5, time.time() + 5))
            self.assertTrue(reloader.poll())
            self.assertEqual((MSFT,), shared.watches)
            self.assertFalse(shared.truth_direct_enabled)

            path.write_text("{not json", encoding="utf-8")
            os.utime(path, (time.time() + 10, time.time() + 10))
            with self.assertLogs(level="ERROR"):
                self.assertFalse(reloader.poll())
            self.assertEqual((MSFT,), shared.watches)


class WatchMatchingTests(unittest.TestCase):
    def test_keyword_matches_whole_word_case_insensitive(self):
        self.assertEqual(("Microsoft",), matching_watches(headline("microsoft outage hits Teams"), [MSFT]))
        self.assertEqual((), matching_watches(headline("MSFTX fund launches"), [MSFT]))

    def test_related_symbol_matches_and_disabled_watch_never_matches(self):
        item = headline("Cloud earnings preview", symbols=("NASDAQ:MSFT",))
        self.assertEqual(("Microsoft",), matching_watches(item, [MSFT]))
        off = Watch(name="Microsoft", keywords=("Microsoft",), enabled=False)
        self.assertEqual((), matching_watches(headline("Microsoft outage"), [off]))


class WatchAlertTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, config, items):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(pathlib.Path(tmp) / "state.db")
            try:
                store.mark_initialized()
                store.set_meta("dtv_news_flow_initialized_at", "2026-10-01T00:00:00+00:00")
                store.begin_notification_session(started_at=time.time() - 30)
                with (
                    patch("trade_alert.app._collect", new=AsyncMock(return_value=(items, True, False, True))),
                    patch("trade_alert.app.notify", return_value=True) as sender,
                ):
                    result = await run_once(config, store, include_official=False)
                return result, sender
            finally:
                store.close()

    async def test_user_watch_alerts_with_watch_name_in_title(self):
        result, sender = await self._run(
            Config(watches=(MSFT,)), [headline("Microsoft 365 outage spreads", item_id="m1")])
        self.assertEqual(1, result["notified"])
        title, body = sender.call_args.args
        self.assertEqual("Trade Alert · Microsoft", title)
        self.assertIn("bevakning Microsoft", body)

    async def test_oil_watch_can_be_switched_off(self):
        oil = headline("Oil supply disruption after pipeline attack", item_id="o1")
        on, _ = await self._run(Config(), [oil])
        off, sender = await self._run(Config(oil_watch_enabled=False), [oil])
        self.assertEqual(1, on["notified"])
        self.assertEqual(0, off["notified"])
        sender.assert_not_called()


class SettingsHelperTests(unittest.TestCase):
    def test_parse_terms_trims_dedupes_and_keeps_order(self):
        self.assertEqual(("Microsoft", "MSFT", "Azure"), parse_terms(" Microsoft, MSFT,,\nAzure, MSFT "))

    def test_apply_settings_updates_shared_config_and_file_or_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch("trade_alert.config.app_dir", return_value=pathlib.Path(tmp)):
            config = Config()
            apply_settings(config, {"truth_direct_enabled": False}, [MSFT])
            self.assertFalse(config.truth_direct_enabled)
            self.assertEqual((MSFT,), Config.load(pathlib.Path(tmp) / "config.json").watches)

            with self.assertRaises(ValueError):
                apply_settings(config, {"oil_watch_enabled": False}, [Watch(name="Tom")])
            self.assertTrue(config.oil_watch_enabled)
            with self.assertRaises(ValueError):
                apply_settings(config, {"poll_seconds": 1}, [])

    def test_monitoring_summary_lists_watches(self):
        summary = monitoring_summary(Config(watches=(MSFT,), oil_watch_enabled=False))
        self.assertIn("Oljebevakning: av", summary)
        self.assertIn("Microsoft — ord: Microsoft, MSFT · symboler: NASDAQ:MSFT", summary)


if __name__ == "__main__":
    unittest.main()
