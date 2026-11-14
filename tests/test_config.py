import json
import pathlib
import tempfile
import unittest

from trade_alert.config import RETIRED_KEYS, Config


class ConfigTests(unittest.TestCase):
    def test_theme_defaults_to_system_for_existing_config_without_theme_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "profile_name": "Oil / Brent",
                        "official_symbols": ["ICEEUR:BRN1!"],
                    }
                ),
                encoding="utf-8",
            )
            config = Config.load(path)
            self.assertEqual("system", config.theme_mode)

    def test_settings_of_removed_features_are_dropped_and_file_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "profile_name": "Oil / Brent",
                        "max_headlines": 25,
                        "trade_spine_url": "http://127.0.0.1:8773/mcp",
                        "official_symbols": ["ICEEUR:BRN1!"],
                        "breaking_inbox_enabled": True,
                        "breaking_authorized_sources": [],
                        "market_correlation_enabled": True,
                        "market_correlation_auto_enable_resident": True,
                        "truth_direct_enabled": False,
                    }
                ),
                encoding="utf-8",
            )
            config = Config.load(path)
            self.assertFalse(config.truth_direct_enabled)
            migrated = json.loads(path.read_text(encoding="utf-8"))
            self.assertFalse(RETIRED_KEYS.intersection(migrated))
            self.assertFalse(migrated["truth_direct_enabled"])

    def test_existing_config_adds_news_flow_replay_overlap(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "profile_name": "Custom",
                        "official_symbols": ["ICEEUR:BRN1!"],
                    }
                ),
                encoding="utf-8",
            )
            config = Config.load(path)
            self.assertEqual(3600, config.dtv_replay_overlap_seconds)
            migrated = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(3600, migrated["dtv_replay_overlap_seconds"])

    def test_theme_mode_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "config.json"
            config = Config(theme_mode="dark")
            config.save(path)
            self.assertEqual("dark", Config.load(path).theme_mode)

    def test_invalid_news_flow_replay_overlap_is_rejected(self):
        with self.assertRaises(ValueError):
            Config(dtv_replay_overlap_seconds=7201).validate()

    def test_invalid_theme_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            Config(theme_mode="neon").validate()


if __name__ == "__main__":
    unittest.main()
