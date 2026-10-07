import json
import pathlib
import tempfile
import unittest

from trade_alert.config import Config


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

    def test_theme_mode_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "config.json"
            config = Config(theme_mode="dark")
            config.save(path)
            self.assertEqual("dark", Config.load(path).theme_mode)

    def test_invalid_theme_mode_is_rejected(self):
        with self.assertRaises(ValueError):
            Config(theme_mode="neon").validate()


if __name__ == "__main__":
    unittest.main()
