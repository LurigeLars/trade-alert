import sys
import types
import unittest
from unittest.mock import patch

from trade_alert import notifier


class NotifierTests(unittest.TestCase):
    def test_windows_toasts_backend_is_used(self):
        calls = []

        class FakeToast:
            def __init__(self):
                self.text_fields = []

        class FakeToaster:
            def __init__(self, app_name):
                calls.append(("init", app_name))

            def show_toast(self, toast):
                calls.append(("show", tuple(toast.text_fields)))

        fake_module = types.SimpleNamespace(Toast=FakeToast, WindowsToaster=FakeToaster)
        with patch.object(notifier.os, "name", "nt"), patch.dict(
            sys.modules, {"windows_toasts": fake_module}
        ):
            self.assertTrue(notifier.notify("Trade Alert", "Test"))

        self.assertEqual(
            [("init", "Trade Alert"), ("show", ("Trade Alert", "Test"))],
            calls,
        )

    def test_backend_failure_is_reported(self):
        class FailingToaster:
            def __init__(self, _app_name):
                raise RuntimeError("boom")

        fake_module = types.SimpleNamespace(Toast=object, WindowsToaster=FailingToaster)
        with patch.object(notifier.os, "name", "nt"), patch.dict(
            sys.modules, {"windows_toasts": fake_module}
        ):
            self.assertFalse(notifier.notify("Trade Alert", "Test"))


if __name__ == "__main__":
    unittest.main()
