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

    def test_existing_alerts_seed_cross_source_seen_identity_on_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "state.db"
            source = "TV:ICEEUR:BRN1!"
            item_id = "te_news:590623:0"
            item_key = f"{source}:{item_id}"

            store = StateStore(path)
            try:
                store.mark_seen(item_key, at=100.0)
                store.record_alert(
                    item_key=item_key,
                    source=source,
                    provider="Trading Economics",
                    headline="Brent Eases on Trump remarks about Iran",
                    body="body",
                    score=3,
                    published=90.0,
                    at=100.0,
                )
                self.assertFalse(store.seen_item(f"trading economics|{item_id}"))
            finally:
                store.close()

            reopened = StateStore(path)
            try:
                self.assertTrue(reopened.seen_item(f"trading economics|{item_id}"))
            finally:
                reopened.close()

    def test_source_observation_is_first_seen_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(pathlib.Path(tmp) / "state.db")
            try:
                key = "trading economics|te_news:590624:0"
                store.mark_source_observations(
                    [(key, "DTV_NEWS_FLOW")],
                    at=100.0,
                )
                store.mark_source_observations(
                    [(key, "DTV_NEWS_FLOW")],
                    at=200.0,
                )
                self.assertEqual(
                    100.0,
                    store.source_first_seen(key, "DTV_NEWS_FLOW"),
                )
            finally:
                store.close()

    def test_alert_history_joins_dtv_first_seen(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(pathlib.Path(tmp) / "state.db")
            try:
                dedupe_key = "trading economics|te_news:590624:0"
                store.mark_source_observations(
                    [(dedupe_key, "DTV_NEWS_FLOW")],
                    at=110.0,
                )
                self.assertTrue(
                    store.record_alert(
                        item_key="TV:ICEEUR:BRN1!:te_news:590624:0",
                        dedupe_key=dedupe_key,
                        source="TV:ICEEUR:BRN1!",
                        provider="Trading Economics",
                        headline="Brent Eases on Trump remarks about Iran",
                        body="body",
                        score=5,
                        published=90.0,
                        at=120.0,
                    )
                )
                row = store.recent_alerts(limit=1)[0]
                self.assertEqual(90.0, row.published)
                self.assertEqual(110.0, row.dtv_first_seen)
                self.assertEqual(120.0, row.created_at)
            finally:
                store.close()

    def test_alert_history_persists_unread_and_marks_only_selected_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(pathlib.Path(tmp) / "state.db")
            try:
                self.assertTrue(
                    store.record_alert(
                        item_key="a",
                        source="TV:ICEEUR:BRN1!",
                        provider="Reuters",
                        headline="Oil supply headline",
                        body="body a",
                        score=4,
                        published=100.0,
                        link="https://example.test/a",
                        at=200.0,
                    )
                )
                self.assertTrue(
                    store.record_alert(
                        item_key="b",
                        source="TV:ICEEUR:BRN1!",
                        provider="Reuters",
                        headline="Second headline",
                        body="body b",
                        score=2,
                        at=201.0,
                    )
                )
                self.assertFalse(
                    store.record_alert(
                        item_key="a",
                        source="TV:ICEEUR:BRN1!",
                        headline="duplicate",
                        body="duplicate",
                        score=2,
                    )
                )
                self.assertEqual(2, store.unread_alert_count())
                rows = store.recent_alerts(limit=10)
                self.assertEqual(["b", "a"], [row.item_key for row in rows])

                store.mark_alerts_read(["a"])
                self.assertEqual(1, store.unread_alert_count())
                self.assertTrue(store.recent_alerts(limit=1)[0].unread)
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
