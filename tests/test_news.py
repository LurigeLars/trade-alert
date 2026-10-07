import time
import unittest

from trade_alert.news import normalize_headlines, relevance_score


class NewsTests(unittest.TestCase):
    def test_normalizes_nested_official_mcp_payload(self):
        payload = {
            "content": [{
                "type": "text",
                "text": '{"success":true,"data":{"headlines":[{"id":"r1","title":"Oil rises after Iran supply disruption","published":1791334765,"provider":{"name":"Reuters"},"urgency":1,"relatedSymbols":[{"symbol":"TVC:UKOIL"}]}]}}',
            }]
        }
        rows = normalize_headlines(payload, source="TV:ICEEUR:BRN1!")
        self.assertEqual(1, len(rows))
        self.assertEqual("Reuters", rows[0].provider)
        self.assertIn("TVC:UKOIL", rows[0].related_symbols)
        self.assertGreaterEqual(relevance_score(rows[0]), 6)

    def test_generic_commodity_technical_headline_is_not_high_relevance(self):
        payload = {"data": {"headlines": [{
            "id": "x", "title": "Commodities intraday targets/key levels",
            "published": time.time(), "provider": {"name": "Reuters"}, "urgency": 2,
        }]}}
        row = normalize_headlines(payload, source="TV")[0]
        self.assertEqual(0, relevance_score(row))

    def test_opec_plus_still_matches_core_term_filter(self):
        payload = {"headlines": [{
            "id": "opec", "title": "OPEC+ ministers meet in Vienna",
            "published": time.time(),
        }]}
        row = normalize_headlines(payload, source="TV")[0]
        self.assertEqual(2, relevance_score(row))

    def test_related_brent_symbol_can_make_geopolitical_headline_relevant(self):
        payload = {"headlines": [{
            "id": "x", "title": "Iran says shipping route faces disruption",
            "published": time.time(), "relatedSymbols": [{"symbol": "TVC:UKOIL"}],
        }]}
        row = normalize_headlines(payload, source="DTV")[0]
        self.assertGreaterEqual(relevance_score(row), 4)


if __name__ == "__main__":
    unittest.main()
