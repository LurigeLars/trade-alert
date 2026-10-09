"""Source-scoped Trump market relevance: impact, noise, and parity tests."""
import pathlib
import tempfile
import time
import unittest
from datetime import datetime, timezone
import json

from trade_alert.chrome_feed import poll_browser_feed
from trade_alert.config import Config
from trade_alert.news import Headline, relevance_score
from trade_alert.state import StateStore
from trade_alert.trump_filter import classify_trump_statement
from trade_alert.truth_direct import _relevance


class TrumpMarketImpactTests(unittest.TestCase):
    def check(self, statement, category, priority, minimum):
        result = classify_trump_statement(statement)
        self.assertEqual(result.category, category, statement)
        self.assertEqual(result.priority, priority, statement)
        self.assertGreaterEqual(result.score, minimum, statement)
        self.assertEqual(_relevance(statement), result.score)
        self.assertLessEqual(result.score, 10)

    def test_high_priority_policy_surprises_across_markets(self):
        samples = [
            ("We are removing Powell as head of the Federal Reserve immediately.",
             "RATES"),
            ("We are imposing 100 percent tariffs on imports from China tomorrow.",
             "TRADE"),
            ("I signed an executive order imposing semiconductor export controls.",
             "TRADE"),
            ("Government shutdown begins tomorrow.", "FISCAL"),
            ("Congress must prevent a US default this week.", "FISCAL"),
            ("NATO will withdraw all troops from the region.", "DEFENSE"),
            ("We are attacking Iran tonight.", "GEOPOLITICS"),
            ("We are banning advanced chips from export to China.", "TRADE"),
        ]
        for text, category in samples:
            with self.subTest(text=text):
                self.check(text, category, "HIGH", 6)

    def test_standard_topic_only_does_not_get_false_high_priority(self):
        for text, cat in [
            ("Met with Chairman Powell today.", "RATES"),
            ("I spoke with the Fed about the economy.", "RATES"),
            ("I visited the Treasury today.", "RATES"),
            ("I met members of Congress yesterday.", "FISCAL"),
            ("I had a good meeting with NATO leaders.", "DEFENSE"),
            ("We are proud of America's semiconductor industry.", "TECH"),
            ("The export controls are being discussed.", "TRADE"),
            ("I love our energy industry.", "ENERGY"),
            ("Iran is a difficult issue.", "GEOPOLITICS"),
        ]:
            with self.subTest(text=text):
                result = classify_trump_statement(text)
                self.assertEqual(result.category, cat)
                self.assertEqual(result.priority, "STANDARD")
                self.assertGreaterEqual(result.score, 2)

    def test_irrelevant_speech_and_potato_chips_are_not_alerts(self):
        for text in [
            "The crowds were wonderful tonight. Thank you all.",
            "I really love potato chips with my hamburgers.",
            "Congratulations to a fantastic golfer on the win.",
            "My wife has a new outfit today.",
            "We made a great deal for the football tickets.",
            "The music was a blast at the event.",
        ]:
            with self.subTest(text=text):
                result = classify_trump_statement(text)
                self.assertEqual(result.priority, "IGNORE")
                self.assertLess(result.score, 2)

    def test_word_boundaries_and_non_oil_generic_feed_stay_unchanged(self):
        self.assertEqual(classify_trump_statement("Unions are proud of their stewardship.").score, 0)
        self.assertEqual(classify_trump_statement("I went to Chipotle.").score, 0)
        generic = Headline(
            source="DTV_NEWS_FLOW", item_id="a",
            title="Powell addressed the Federal Reserve", published=None
        )
        # The broad macro vocabulary must not leak into DTV's oil news scoring.
        self.assertEqual(relevance_score(generic), 0)
        oil = Headline(
            source="DTV_NEWS_FLOW", item_id="b",
            title="Oil supply disrupted by Iranian tanker strike", published=None
        )
        self.assertGreaterEqual(relevance_score(oil), 4)

    def test_legacy_energy_recall_remains(self):
        for term in ("oil", "crude", "opec", "hormuz", "venezuela",
                     "tariffs", "federal reserve", "nuclear"):
            self.assertGreaterEqual(_relevance(term), 2, term)


class ChromePriorityIntegrationTests(unittest.TestCase):
    def test_chrome_pipeline_persists_category_and_urgency_without_new_state(self):
        with tempfile.TemporaryDirectory() as d:
            base = pathlib.Path(d)
            store = StateStore(base / "alerts.sqlite")
            try:
                now = time.time()
                post = {
                    "id":"117406186276133332",
                    "created_at":datetime.fromtimestamp(
                        now - 5, timezone.utc
                    ).isoformat().replace("+00:00", "Z"),
                    "visibility":"public",
                    "account":{"id":"107780257626128497",
                               "acct":"realDonaldTrump",
                               "username":"realDonaldTrump"},
                    "content":"<p>Fed will fire Powell immediately over rates.</p>",
                    "media_attachments":[],
                }
                incoming = base / "post-117406186276133332.json"
                incoming.write_text(json.dumps(post), encoding="utf-8")
                toasts = []
                result = poll_browser_feed(
                    Config(chrome_bridge_enabled=True, truth_direct_enabled=False,
                           truth_rss_enabled=False),
                    store, directory=base, at=now,
                    notification=lambda *args: toasts.append(args) or True
                )
                self.assertEqual(result["alerts"], 1)
                self.assertEqual(result["notified"], 1)
                self.assertIn("HIGH", toasts[0][0])
                self.assertIn("RATES", toasts[0][0])
                self.assertEqual(len(store.recent_alerts()), 1)
                self.assertFalse(incoming.exists())
            finally:
                store.close()


if __name__ == "__main__":
    unittest.main()
