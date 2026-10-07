import time
import unittest
from unittest.mock import AsyncMock, patch

from trade_alert.mcp_client import MCPToolError
from trade_alert.news import (
    DTVWatchlistContext,
    fetch_dtv_news,
    normalize_headlines,
    relevance_score,
    resolve_dtv_watchlist,
)


class NewsTests(unittest.IsolatedAsyncioTestCase):
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

    def test_hormuz_is_relevant_without_oil_symbol_context(self):
        payload = {"headlines": [{
            "id": "hormuz", "title": "Iran says routes through Strait of Hormuz will be blocked",
            "published": time.time(),
        }]}
        row = normalize_headlines(payload, source="DTV_NEWS_FLOW")[0]
        self.assertGreaterEqual(relevance_score(row), 4)

    def test_impact_word_without_oil_context_does_not_alert(self):
        payload = {"headlines": [{
            "id": "deal", "title": "Software company announces strategic deal",
            "published": time.time(),
        }]}
        row = normalize_headlines(payload, source="DTV_NEWS_FLOW")[0]
        self.assertEqual(0, relevance_score(row))

    def test_related_oil_symbol_is_routing_evidence_not_alert_by_itself(self):
        payload = {"headlines": [{
            "id": "macro", "title": "Markets open mixed after overnight session",
            "published": time.time(),
            "related_symbols": [{"symbol": "TVC:USOIL"}],
        }]}
        row = normalize_headlines(payload, source="DTV_NEWS_FLOW")[0]
        self.assertEqual(1, relevance_score(row))

    def test_related_oil_symbol_plus_geopolitical_impact_is_relevant(self):
        payload = {"headlines": [{
            "id": "x", "title": "Iran says shipping route faces disruption",
            "published": time.time(), "relatedSymbols": [{"symbol": "TVC:UKOIL"}],
        }]}
        row = normalize_headlines(payload, source="DTV_NEWS_FLOW")[0]
        self.assertGreaterEqual(relevance_score(row), 3)

    async def test_auto_resolves_active_watchlist_with_oil_anchor(self):
        payload = {
            "success": True,
            "list_id": 341892775,
            "list_name": "Watchlist",
            "symbols": [
                {"symbol": "NASDAQ:NVDA"},
                {"symbol": "TVC:USOIL"},
            ],
        }
        with patch("trade_alert.news.call_json_tool", new=AsyncMock(return_value=payload)):
            context = await resolve_dtv_watchlist(url="http://127.0.0.1:8765/mcp")

        self.assertEqual("341892775", context.watchlist_id)
        self.assertEqual("Watchlist", context.name)
        self.assertTrue(context.auto_discovered)
        self.assertIn("TVC:USOIL", context.symbols)

    async def test_auto_resolve_rejects_watchlist_without_oil_anchor(self):
        payload = {
            "success": True,
            "list_id": 123,
            "list_name": "Tech only",
            "symbols": [{"symbol": "NASDAQ:NVDA"}],
        }
        with patch("trade_alert.news.call_json_tool", new=AsyncMock(return_value=payload)):
            with self.assertRaises(MCPToolError):
                await resolve_dtv_watchlist(url="http://127.0.0.1:8765/mcp")

    async def test_news_flow_reports_incomplete_freshness_boundary(self):
        context = DTVWatchlistContext(
            watchlist_id="341892775",
            name="Watchlist",
            symbols=("TVC:USOIL",),
            auto_discovered=True,
        )
        payload = {
            "success": True,
            "source_window_truncated": True,
            "freshness_boundary_reached": False,
            "items": [{
                "id": "oil",
                "title": "Oil rises after supply disruption",
                "published": time.time(),
            }],
        }
        with patch("trade_alert.news.call_json_tool", new=AsyncMock(return_value=payload)):
            batch = await fetch_dtv_news(
                url="http://127.0.0.1:8765/mcp",
                context=context,
                since="2026-10-07T10:00:00Z",
                limit=200,
            )

        self.assertFalse(batch.coverage_complete)
        self.assertEqual(1, len(batch.headlines))


if __name__ == "__main__":
    unittest.main()
