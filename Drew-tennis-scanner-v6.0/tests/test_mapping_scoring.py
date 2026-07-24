import json
import unittest
from pathlib import Path

from scanner.decision import evaluate_match
from scanner.event_pipeline import build_pipeline
from scanner.live_mapping import build_live_scanner_mapping, normalize_game_score
from scanner.live_scan import scan_both_players
from scanner.models import MatchInput
from scanner.scoring import calculate_stability_score

FIXTURE = Path(__file__).parent / "fixtures" / "live_tennis_events.json"


def eligible_match(**overrides):
    values = dict(
        player="Player A", opponent="Player B", tournament="Test", surface="Unknown",
        market_price_cents=98.0, bankroll=100.0, match_closing_set=True,
        break_lead=2, serving=True, tiebreak=False, backed_player_games_in_set=5,
        current_game_score="40-0", completed_sets=1, breaks_suffered_by_set=[0],
        service_points_won_pct=72.0, current_set_service_points_won_pct=75.0,
        effective_service_points_won_pct=73.0, opponent_service_points_won_pct=48.0,
        opponent_current_set_service_points_won_pct=45.0, first_serve_points_won_pct=82.0,
        current_set_first_serve_points_won_pct=84.0, first_serve_in_pct=72.0,
        current_set_first_serve_in_pct=74.0, breaks_suffered_total=0,
        current_set_breaks_suffered=0, break_points_created=5, break_points_faced=0,
        comfortable_holds_pct=80.0, double_faults_per_service_game=0.1,
        recent_form_label="Very poor", ranking=5, opponent_ranking=350, surface_form_label="Weak",
        data_completeness_pct=100.0, core_completeness_pct=100.0,
    )
    values.update(overrides)
    return MatchInput(**values)


class PerspectiveTests(unittest.TestCase):
    def test_game_score_reverses_for_second_player(self):
        self.assertEqual(normalize_game_score("40 - 15", "First Player", False), "40-15")
        self.assertEqual(normalize_game_score("40 - 15", "Second Player", False), "15-40")

    def test_uploaded_sample_scans_every_supported_player(self):
        events = json.loads(FIXTURE.read_text())
        pipeline = build_pipeline(events)
        self.assertEqual(len(pipeline.supported_events), 2)
        total = 0
        for event in pipeline.supported_events:
            results = scan_both_players(event, rankings={}, price_by_player={}, bankroll=0)
            self.assertEqual(len(results), 2)
            self.assertEqual(
                [result.player for result in results],
                [event["event_first_player"], event["event_second_player"]],
            )
            self.assertTrue(all(result.error is None for result in results))
            total += len(results)
        self.assertEqual(total, 4)

    def test_missing_every_optional_stat_still_returns_two_results(self):
        event = {
            "event_key": "m15",
            "event_first_player": "A. Alpha",
            "event_second_player": "B. Beta",
            "first_player_key": 1,
            "second_player_key": 2,
            "event_type_type": "Itf Men Singles",
            "tournament_name": "ITF M15 Test Men",
            "event_status": "Set 2",
            "event_final_result": "1 - 0",
            "event_game_result": "0 - 0",
            "scores": [{"score_set": "2", "score_first": "4", "score_second": "2"}],
            "statistics": [],
            "pointbypoint": [],
        }
        results = scan_both_players(event, rankings={}, bankroll=0)
        self.assertEqual(len(results), 2)
        self.assertTrue(all(result.decision.score >= 0 for result in results))
        self.assertTrue(all(result.mapping.data_completeness_pct < 100 for result in results))

    def test_mapping_uses_real_statistics_from_sample(self):
        events = json.loads(FIXTURE.read_text())
        event = next(row for row in events if row.get("event_key") == 12147766)
        player = event["event_first_player"]
        mapping = build_live_scanner_mapping(event, player, rankings={})
        self.assertGreater(mapping.updates["scan_service_points"], 0)
        self.assertGreater(mapping.updates["scan_first_serve_points"], 0)
        self.assertTrue(mapping.field_status["service_points_won_pct"].available)


class ScoreAndOptionalTests(unittest.TestCase):
    def test_surface_and_form_do_not_change_score(self):
        first = eligible_match(recent_form_label="Excellent", surface_form_label="Strong", surface="Grass")
        second = eligible_match(recent_form_label="Poor", surface_form_label="Weak", surface="Clay")
        self.assertEqual(calculate_stability_score(first)[0], calculate_stability_score(second)[0])

    def test_missing_price_still_scans(self):
        decision = evaluate_match(eligible_match(market_price_cents=0.0))
        self.assertEqual(decision.status, "TRADE")
        self.assertGreater(decision.score, 0)

    def test_zero_bankroll_still_allows_trade_decision(self):
        decision = evaluate_match(eligible_match(bankroll=0.0))
        self.assertEqual(decision.status, "TRADE")
        self.assertEqual(decision.stake_amount, 0.0)

    def test_missing_optional_stats_do_not_raise(self):
        match = eligible_match(
            service_points_won_pct=None,
            first_serve_points_won_pct=None,
            first_serve_in_pct=None,
            breaks_suffered_total=None,
            break_points_faced=None,
            comfortable_holds_pct=None,
            double_faults_per_service_game=None,
            ranking=None,
        )
        decision = evaluate_match(match)
        self.assertIsInstance(decision.score, float)
        self.assertLess(decision.scoring_completeness_pct, 100)


if __name__ == "__main__":
    unittest.main()
