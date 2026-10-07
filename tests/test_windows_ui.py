import os
import unittest

from trade_alert.windows_ui import configure_windows_dpi_awareness


class WindowsDpiTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
