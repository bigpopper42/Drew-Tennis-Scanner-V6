import unittest
from unittest.mock import patch

from scanner.polymarket import (
    extract_bbo_prices,
    infer_player_market_side,
    infer_player_prices,
    match_tennis_market,
)


def row(p1="A. Alpha", p2="B. Beta", live=True, title=None):
    return {
        "event_id": "1",
        "event_title": title or f"{p1} vs {p2} - ITF M15 Phoenix",
        "event_slug": "alpha-beta-itf-m15-phoenix",
        "event_live": live,
        "player1": p1,
        "player2": p2,
        "market_id": "m1",
        "market_title": f"Will {p1} win the match?",
        "market_slug": "alpha-win",
        "match_winner_market": True,
        "series_slug": "itf-m15-phoenix",
        "sides": [{"name": "Yes"}, {"name": "No"}],
        "raw_market": {"question": f"Will {p1} win the match?", "sides": [{"name": "Yes"}, {"name": "No"}]},
        "raw_event": {"subtitle": "ITF M15 Phoenix"},
    }


class MarketLookupTests(unittest.TestCase):
    @patch("scanner.polymarket._paginate_events")
    @patch("scanner.polymarket.search_us_markets")
    def test_itf_lookup_uses_search_and_sport_fallback(self, search, paginate):
        search.side_effect = lambda query, **kwargs: [row()] if "Alpha" in query and "Beta" in query else []
        paginate.return_value = []
        matches = match_tennis_market(
            "A. Alpha", "B. Beta", league="ATP", competition_group="ITF", tournament="ITF M15 Phoenix Men"
        )
        self.assertTrue(matches)
        self.assertGreaterEqual(matches[0]["api_match_confidence"], 80)
        self.assertTrue(any("search:" in call.get("lookup_source", "") for call in matches))


    @patch("scanner.polymarket._paginate_events")
    @patch("scanner.polymarket.search_us_markets")
    def test_strong_exact_pair_stops_extra_network_searches(self, search, paginate):
        search.return_value = [row()]
        matches = match_tennis_market("A. Alpha", "B. Beta", competition_group="ITF")
        self.assertTrue(matches)
        self.assertEqual(search.call_count, 1)
        paginate.assert_not_called()

    @patch("scanner.polymarket._flatten_events")
    @patch("scanner.polymarket._paginate_events")
    @patch("scanner.polymarket.search_us_markets")
    def test_sport_fallback_recovers_search_miss(self, search, paginate, flatten):
        search.return_value = []
        paginate.return_value = [{"id": "event"}]
        flatten.return_value = [row()]
        matches = match_tennis_market("A. Alpha", "B. Beta", competition_group="ITF")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["lookup_source"], "sport:tennis")

    def test_bbo_and_both_player_price_inference(self):
        bbo = {
            "marketData": {
                "bestAsk": {"value": "0.98"},
                "bestBid": {"value": "0.97"},
            }
        }
        prices = extract_bbo_prices(bbo)
        market = row()
        self.assertEqual(infer_player_market_side(market, "A. Alpha", "B. Beta"), "Long / YES")
        self.assertEqual(infer_player_market_side(market, "B. Beta", "A. Alpha"), "Short / NO")
        inferred = infer_player_prices(market, "A. Alpha", "B. Beta", prices)
        self.assertEqual(inferred["prices"]["A. Alpha"], 98.0)
        self.assertEqual(inferred["prices"]["B. Beta"], 3.0)


if __name__ == "__main__":
    unittest.main()
