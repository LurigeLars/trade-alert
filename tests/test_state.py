import pathlib
import tempfile
import unittest

from trade_alert.state import StateStore


class StateTests(unittest.TestCase):
    def test_seen_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(pathlib.Path(tmp) / "state.db")
            try:
                self.assertFalse(store.seen("a"))
                store.mark_seen("a")
                store.mark_seen("a")
                self.assertTrue(store.seen("a"))
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
