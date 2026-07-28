import unittest
from unittest.mock import patch

from scanner.polymarket import (
    _build_match_row,
    _flatten_events,
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

    def test_current_market_sides_map_kwon_and_winter_without_guessing(self):
        market = {
            "market_title": "S. Kwon vs E. Winter",
            "raw_market": {
                "sportsMarketType": "tennis_match_winner",
                "marketSides": [
                    {"long": True, "team": {"name": "Soonwoo Kwon"}},
                    {"long": False, "team": {"name": "Edward Winter"}},
                ],
            },
        }
        self.assertEqual(
            infer_player_market_side(market, "S. Kwon", "E. Winter"),
            "Long / YES",
        )
        self.assertEqual(
            infer_player_market_side(market, "E. Winter", "S. Kwon"),
            "Short / NO",
        )


    def test_exact_score_prop_cannot_outrank_match_winner_moneyline(self):
        event = {
            "id": "arnaldi-musetti",
            "title": "Matteo Arnaldi vs Lorenzo Musetti",
            "teams": [
                {"name": "Matteo Arnaldi"},
                {"name": "Lorenzo Musetti"},
            ],
            "markets": [
                {
                    "id": "exact",
                    "slug": "astatc-atp-matarn-lormus-2026-07-27-es-0-2",
                    "question": "Musetti wins 2-0",
                    "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP",
                    "active": True,
                    "closed": False,
                    "marketSides": [
                        {"long": True, "team": {"name": "Lorenzo Musetti"}},
                        {"long": False, "team": {"name": "Matteo Arnaldi"}},
                    ],
                },
                {
                    "id": "moneyline",
                    "slug": "aec-atp-matarn-lormus-2026-07-27",
                    "question": "Matteo Arnaldi vs Lorenzo Musetti",
                    "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
                    "active": True,
                    "closed": False,
                    "marketSides": [
                        {"long": True, "team": {"name": "Matteo Arnaldi"}},
                        {"long": False, "team": {"name": "Lorenzo Musetti"}},
                    ],
                },
            ],
        }

        selected = _build_match_row(event)

        self.assertEqual(selected["market_id"], "moneyline")
        self.assertEqual(
            selected["market_type"], "SPORTS_MARKET_TYPE_MONEYLINE"
        )
        self.assertTrue(selected["match_winner_market"])

    def test_exact_score_text_is_rejected_even_with_wrong_moneyline_type(self):
        event = {
            "id": "bad-type-exact-score",
            "title": "Matteo Arnaldi vs Lorenzo Musetti",
            "teams": [
                {"name": "Matteo Arnaldi"},
                {"name": "Lorenzo Musetti"},
            ],
            "markets": [
                {
                    "id": "bad-type",
                    "slug": "musetti-special",
                    "question": "Lorenzo Musetti 2-0",
                    "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_MONEYLINE",
                    "active": True,
                    "closed": False,
                    "marketSides": [
                        {"long": True, "team": {"name": "Lorenzo Musetti"}},
                        {"long": False, "team": {"name": "Matteo Arnaldi"}},
                    ],
                }
            ],
        }

        selected = _build_match_row(event)

        self.assertFalse(selected["match_winner_market"])
        self.assertIsNone(selected["market_id"])

    def test_sets_to_zero_wording_is_rejected_without_market_type(self):
        event = {
            "id": "worded-exact-score",
            "title": "Matteo Arnaldi vs Lorenzo Musetti",
            "teams": [
                {"name": "Matteo Arnaldi"},
                {"name": "Lorenzo Musetti"},
            ],
            "markets": [
                {
                    "id": "worded-prop",
                    "slug": "musetti-win-two-sets",
                    "question": "Will Musetti win 2 sets to 0?",
                    "active": True,
                    "closed": False,
                    "marketSides": [
                        {"long": True, "team": {"name": "Lorenzo Musetti"}},
                        {"long": False, "team": {"name": "Matteo Arnaldi"}},
                    ],
                }
            ],
        }

        selected = _build_match_row(event)

        self.assertFalse(selected["match_winner_market"])
        self.assertIsNone(selected["market_id"])

    def test_exact_score_only_event_has_no_safe_match_winner_market(self):
        event = {
            "id": "exact-only",
            "title": "Matteo Arnaldi vs Lorenzo Musetti",
            "teams": [
                {"name": "Matteo Arnaldi"},
                {"name": "Lorenzo Musetti"},
            ],
            "markets": [
                {
                    "id": "exact",
                    "slug": "astatc-atp-matarn-lormus-2026-07-27-es-0-2",
                    "question": "Musetti wins 2-0",
                    "sportsMarketTypeV2": "SPORTS_MARKET_TYPE_PROP",
                    "active": True,
                    "closed": False,
                    "marketSides": [
                        {"long": True, "team": {"name": "Lorenzo Musetti"}},
                        {"long": False, "team": {"name": "Matteo Arnaldi"}},
                    ],
                }
            ],
        }

        selected = _build_match_row(event)

        self.assertFalse(selected["match_winner_market"])
        self.assertIsNone(selected["market_id"])
        self.assertFalse(selected["market_slug"])

    @patch("scanner.polymarket._paginate_events")
    @patch("scanner.polymarket.search_us_markets")
    def test_current_teams_and_market_sides_match_mayo_pascual(self, search, paginate):
        event = {
            "id": "los-cabos-1",
            "title": "ATP Los Cabos Open, Qualification",
            "slug": "atp-los-cabos-qualification",
            "live": True,
            "teams": [
                {"name": "Aidan Mayo"},
                {"name": "Reynaldo Pascual Ferra"},
            ],
            "markets": [
                {
                    "id": "mayo-pascual",
                    "slug": "aec-atp-aidmay-reypas-2026-07-26",
                    "sportsMarketType": "tennis_match_winner",
                    "active": True,
                    "closed": False,
                    "marketSides": [
                        {"long": True, "team": {"name": "Aidan Mayo"}},
                        {
                            "long": False,
                            "team": {"name": "Reynaldo Pascual Ferra"},
                        },
                    ],
                }
            ],
        }
        search.return_value = _flatten_events([event])
        paginate.return_value = []

        matches = match_tennis_market(
            "A. Mayo",
            "R. Pascual Ferra",
            league="ATP",
            competition_group="TOUR",
            tournament="Los Cabos",
        )

        self.assertTrue(matches)
        self.assertGreaterEqual(matches[0]["api_match_confidence"], 80)
        self.assertEqual(
            infer_player_market_side(
                matches[0], "A. Mayo", "R. Pascual Ferra"
            ),
            "Long / YES",
        )


if __name__ == "__main__":
    unittest.main()
