import unittest

from trade_alert.tray import make_status_icon


class TrayTests(unittest.TestCase):
    def test_status_icons_are_runtime_generated_rgba_images(self):
        for health in ("ok", "waiting", "error", "paused"):
            image = make_status_icon(health)
            self.assertEqual((64, 64), image.size)
            self.assertEqual("RGBA", image.mode)


if __name__ == "__main__":
    unittest.main()
