import os
import unittest

from trade_alert.windows_ui import (
    PREFERRED_APP_MODE_ALLOW_DARK,
    PREFERRED_APP_MODE_FORCE_DARK,
    PREFERRED_APP_MODE_FORCE_LIGHT,
    configure_windows_app_identity,
    configure_windows_dpi_awareness,
    configure_windows_native_menu_theme,
    preferred_app_mode,
)


class WindowsDpiTests(unittest.TestCase):
    def test_app_identity_rejects_invalid_ids(self):
        with self.assertRaises(ValueError):
            configure_windows_app_identity("")
        with self.assertRaises(ValueError):
            configure_windows_app_identity("x" * 129)

    @unittest.skipUnless(os.name == "nt", "Windows-only AppUserModelID API")
    def test_app_identity_configuration_is_nonfatal(self):
        result = configure_windows_app_identity()
        self.assertTrue(
            result == "set"
            or result == "unavailable"
            or result.startswith("hresult-0x")
        )

    def test_preferred_app_mode_mapping(self):
        self.assertEqual(PREFERRED_APP_MODE_ALLOW_DARK, preferred_app_mode("system"))
        self.assertEqual(PREFERRED_APP_MODE_FORCE_DARK, preferred_app_mode("dark"))
        self.assertEqual(PREFERRED_APP_MODE_FORCE_LIGHT, preferred_app_mode("light"))
        with self.assertRaises(ValueError):
            preferred_app_mode("invalid")

    @unittest.skipUnless(os.name == "nt", "Windows-only DPI API")
    def test_process_dpi_awareness_is_configured_or_already_set(self):
        result = configure_windows_dpi_awareness()
        self.assertIn(
            result,
            {
                "per-monitor-v2",
                "per-monitor",
                "system-aware",
                "already-set",
            },
        )

        # DPI awareness is process-global and may only be set once.
        second = configure_windows_dpi_awareness()
        self.assertIn(second, {"already-set", result})

    @unittest.skipUnless(os.name == "nt", "Windows-only native menu API")
    def test_native_menu_theme_configuration_is_nonfatal(self):
        try:
            dark = configure_windows_native_menu_theme("dark")
            light = configure_windows_native_menu_theme("light")
            system = configure_windows_native_menu_theme("system")
        finally:
            configure_windows_native_menu_theme("system")

        allowed = {
            "force-dark", "force-dark-no-flush",
            "force-light", "force-light-no-flush",
            "allow-dark", "allow-dark-no-flush",
            "unsupported", "unavailable",
        }
        self.assertIn(dark, allowed)
        self.assertIn(light, allowed)
        self.assertIn(system, allowed)


if __name__ == "__main__":
    unittest.main()
