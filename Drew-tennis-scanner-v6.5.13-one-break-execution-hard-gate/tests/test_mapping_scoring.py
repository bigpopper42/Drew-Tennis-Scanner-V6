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

    def test_duplicate_point_rows_cannot_fabricate_two_breaks_at_one_zero(self):
        break_game = {
            "set_number": "Set 2",
            "number_game": "1",
            "player_served": "Second Player",
            "serve_winner": "First Player",
            "score": "1 - 0",
            "points": [],
        }
        stale_future_game = {
            "set_number": "Set 2",
            "number_game": "2",
            "player_served": "Second Player",
            "serve_winner": "First Player",
            "score": "2 - 0",
            "points": [],
        }
        event = {
            "event_key": "duplicate-break-test",
            "event_first_player": "A. Alpha",
            "event_second_player": "B. Beta",
            "first_player_key": 1,
            "second_player_key": 2,
            "event_type_type": "Atp Singles",
            "tournament_name": "ATP Test",
            "event_status": "Set 2",
            "event_final_result": "1 - 0",
            "event_game_result": "0 - 0",
            "event_serve": "First Player",
            "scores": [{"score_set": "2", "score_first": "1", "score_second": "0"}],
            "statistics": [],
            "pointbypoint": [break_game, dict(break_game), stale_future_game],
        }

        mapping = build_live_scanner_mapping(event, "A. Alpha", rankings={})

        self.assertEqual(mapping.updates["scan_break_lead"], 1)

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


class OneBreakMaturityRuleTests(unittest.TestCase):
    def test_one_break_three_games_unbroken_is_blocked(self):
        match = eligible_match(
            break_lead=1,
            backed_player_games_in_set=3,
            opponent_games_in_set=1,
            current_set_breaks_suffered=0,
            serving=True,
            current_game_score="40-0",
        )
        decision = evaluate_match(match)
        self.assertEqual(decision.status, "NO TRADE")
        self.assertTrue(any("requires at least 4 games won" in item for item in decision.concerns))

    def test_one_break_four_games_unbroken_can_pass_maturity_gate(self):
        match = eligible_match(
            break_lead=1,
            backed_player_games_in_set=4,
            opponent_games_in_set=2,
            current_set_breaks_suffered=0,
            serving=True,
            current_game_score="40-0",
        )
        decision = evaluate_match(match)
        self.assertEqual(decision.status, "TRADE")
        self.assertTrue(any("One-break maturity gate passed" in item for item in decision.passed))

    def test_one_break_four_games_after_being_broken_once_is_blocked(self):
        match = eligible_match(
            break_lead=1,
            backed_player_games_in_set=4,
            opponent_games_in_set=2,
            current_set_breaks_suffered=1,
            serving=True,
            current_game_score="40-0",
        )
        decision = evaluate_match(match)
        self.assertEqual(decision.status, "NO TRADE")
        self.assertTrue(any("requires at least 5 games won" in item for item in decision.concerns))

    def test_one_break_five_games_after_being_broken_once_can_pass_maturity_gate(self):
        match = eligible_match(
            break_lead=1,
            backed_player_games_in_set=5,
            opponent_games_in_set=3,
            current_set_breaks_suffered=1,
            serving=True,
            current_game_score="40-0",
        )
        decision = evaluate_match(match)
        self.assertEqual(decision.status, "TRADE")
        self.assertTrue(any("One-break maturity gate passed" in item for item in decision.passed))

    def test_two_break_lead_is_not_delayed_by_new_one_break_rule(self):
        match = eligible_match(
            break_lead=2,
            backed_player_games_in_set=2,
            opponent_games_in_set=0,
            current_set_breaks_suffered=0,
        )
        decision = evaluate_match(match)
        self.assertEqual(decision.status, "TRADE")


class QualificationVolatilityRuleTests(unittest.TestCase):
    def test_top_150_backed_player_can_face_any_ranked_opponent(self):
        decision = evaluate_match(eligible_match(is_qualification=True, ranking=150, opponent_ranking=233))
        self.assertEqual(decision.status, "TRADE")

    def test_top_150_backed_player_can_face_missing_opponent_rank(self):
        decision = evaluate_match(eligible_match(is_qualification=True, ranking=92, opponent_ranking=None))
        self.assertEqual(decision.status, "TRADE")

    def test_rank_151_requires_opponent_450_or_worse(self):
        blocked = evaluate_match(eligible_match(is_qualification=True, ranking=151, opponent_ranking=449))
        allowed = evaluate_match(eligible_match(is_qualification=True, ranking=151, opponent_ranking=450))
        self.assertEqual(blocked.status, "NO TRADE")
        self.assertEqual(allowed.status, "TRADE")

    def test_rank_200_still_uses_450_cutoff(self):
        allowed = evaluate_match(eligible_match(is_qualification=True, ranking=200, opponent_ranking=450))
        self.assertEqual(allowed.status, "TRADE")

    def test_rank_151_to_200_requires_known_opponent_rank(self):
        decision = evaluate_match(eligible_match(is_qualification=True, ranking=175, opponent_ranking=None))
        self.assertEqual(decision.status, "NO TRADE")
        self.assertTrue(any("151-200" in item and "450" in item for item in decision.concerns))

    def test_rank_201_requires_opponent_750_or_worse(self):
        blocked = evaluate_match(eligible_match(is_qualification=True, ranking=201, opponent_ranking=749))
        allowed = evaluate_match(eligible_match(is_qualification=True, ranking=201, opponent_ranking=750))
        self.assertEqual(blocked.status, "NO TRADE")
        self.assertEqual(allowed.status, "TRADE")

    def test_rank_250_still_uses_750_cutoff(self):
        allowed = evaluate_match(eligible_match(is_qualification=True, ranking=250, opponent_ranking=750))
        self.assertEqual(allowed.status, "TRADE")

    def test_rank_201_to_250_requires_known_opponent_rank(self):
        decision = evaluate_match(eligible_match(is_qualification=True, ranking=225, opponent_ranking=None))
        self.assertEqual(decision.status, "NO TRADE")
        self.assertTrue(any("201-250" in item and "750" in item for item in decision.concerns))

    def test_rank_251_or_worse_is_blocked_in_qualifier(self):
        decision = evaluate_match(eligible_match(is_qualification=True, ranking=251, opponent_ranking=900))
        self.assertEqual(decision.status, "NO TRADE")
        self.assertTrue(any("#251 or worse" in item for item in decision.concerns))

    def test_missing_backed_player_ranking_is_blocked(self):
        decision = evaluate_match(eligible_match(is_qualification=True, ranking=None, opponent_ranking=900))
        self.assertEqual(decision.status, "NO TRADE")
        self.assertTrue(any("verified ATP ranking for the backed player" in item for item in decision.concerns))

    def test_low_ranked_main_draw_is_not_blocked_by_qualification_gate(self):
        decision = evaluate_match(eligible_match(is_qualification=False, ranking=318, opponent_ranking=427))
        self.assertEqual(decision.status, "TRADE")


class FreshBreakConsolidationRuleTests(unittest.TestCase):
    def test_fresh_break_at_four_blocks_before_40_love(self):
        decision = evaluate_match(
            eligible_match(
                break_lead=1,
                backed_player_games_in_set=4,
                opponent_games_in_set=3,
                current_set_breaks_suffered=0,
                serving=True,
                current_game_score="30-0",
                last_completed_game_was_break_by_backed=True,
                current_service_game_reached_30_0=True,
                current_service_game_reached_40_0=False,
            )
        )
        self.assertEqual(decision.status, "NO TRADE")
        self.assertTrue(any("requires reaching 40-0" in item for item in decision.concerns))

    def test_fresh_break_at_four_passes_after_reaching_40_love(self):
        decision = evaluate_match(
            eligible_match(
                break_lead=1,
                backed_player_games_in_set=4,
                opponent_games_in_set=3,
                current_set_breaks_suffered=0,
                serving=True,
                current_game_score="40-15",
                last_completed_game_was_break_by_backed=True,
                current_service_game_reached_30_0=True,
                current_service_game_reached_40_0=True,
            )
        )
        self.assertEqual(decision.status, "TRADE")
        self.assertTrue(any("reaching 40-0" in item for item in decision.passed))

    def test_fresh_break_at_five_blocks_before_30_love(self):
        decision = evaluate_match(
            eligible_match(
                break_lead=1,
                backed_player_games_in_set=5,
                opponent_games_in_set=4,
                current_set_breaks_suffered=0,
                serving=True,
                serving_for_match=True,
                current_game_score="15-0",
                last_completed_game_was_break_by_backed=True,
                current_service_game_reached_30_0=False,
                current_service_game_reached_40_0=False,
            )
        )
        self.assertEqual(decision.status, "NO TRADE")
        self.assertTrue(any("requires reaching 30-0" in item for item in decision.concerns))

    def test_fresh_break_at_five_passes_after_reaching_30_love(self):
        decision = evaluate_match(
            eligible_match(
                break_lead=1,
                backed_player_games_in_set=5,
                opponent_games_in_set=4,
                current_set_breaks_suffered=0,
                serving=True,
                serving_for_match=True,
                current_game_score="30-0",
                last_completed_game_was_break_by_backed=True,
                current_service_game_reached_30_0=True,
                current_service_game_reached_40_0=False,
            )
        )
        self.assertEqual(decision.status, "TRADE")
        self.assertTrue(any("reaching 30-0" in item for item in decision.passed))

    def test_old_already_consolidated_break_does_not_use_fresh_break_gate(self):
        decision = evaluate_match(
            eligible_match(
                break_lead=1,
                backed_player_games_in_set=4,
                opponent_games_in_set=2,
                current_set_breaks_suffered=0,
                serving=True,
                current_game_score="30-0",
                last_completed_game_was_break_by_backed=False,
                current_service_game_reached_30_0=True,
                current_service_game_reached_40_0=False,
            )
        )
        self.assertEqual(decision.status, "TRADE")


class FreshBreakMappingTests(unittest.TestCase):
    def test_mapping_remembers_break_and_service_game_score_history(self):
        event = {
            "event_key": "fresh-break-four",
            "event_first_player": "A. Alpha",
            "event_second_player": "B. Beta",
            "first_player_key": 1,
            "second_player_key": 2,
            "event_type_type": "ATP Singles",
            "tournament_name": "ATP Test",
            "tournament_round": "ATP Test - 1/8-finals",
            "event_qualification": "False",
            "event_status": "Set 2",
            "event_final_result": "1 - 0",
            "event_game_result": "40 - 15",
            "event_serve": "First Player",
            "scores": [{"score_set": "2", "score_first": "4", "score_second": "3"}],
            "statistics": [],
            "pointbypoint": [
                {
                    "set_number": "Set 2",
                    "number_game": "7",
                    "player_served": "Second Player",
                    "serve_winner": "First Player",
                    "score": "4 - 3",
                    "points": [],
                },
                {
                    "set_number": "Set 2",
                    "number_game": "8",
                    "player_served": "First Player",
                    "serve_winner": None,
                    "score": None,
                    "points": [
                        {"number_point": "1", "score": "15 - 0"},
                        {"number_point": "2", "score": "30 - 0"},
                        {"number_point": "3", "score": "40 - 0"},
                        {"number_point": "4", "score": "40 - 15"},
                    ],
                },
            ],
        }
        mapping = build_live_scanner_mapping(event, "A. Alpha", rankings={1: 90, 2: 120})
        self.assertTrue(mapping.updates["scan_last_game_break_by_backed"])
        self.assertTrue(mapping.updates["scan_current_service_reached_30_0"])
        self.assertTrue(mapping.updates["scan_current_service_reached_40_0"])
        self.assertFalse(mapping.updates["scan_is_qualification"])

    def test_mapping_marks_qualification_from_api_flag(self):
        event = {
            "event_key": "qualifier",
            "event_first_player": "A. Alpha",
            "event_second_player": "B. Beta",
            "first_player_key": 1,
            "second_player_key": 2,
            "event_type_type": "ATP Singles",
            "tournament_name": "Astana Challenger",
            "tournament_round": "Qualification final",
            "event_qualification": "True",
            "event_status": "Set 2",
            "event_final_result": "1 - 0",
            "event_game_result": "0 - 0",
            "event_serve": "First Player",
            "scores": [{"score_set": "2", "score_first": "5", "score_second": "3"}],
            "statistics": [],
            "pointbypoint": [],
        }
        mapping = build_live_scanner_mapping(event, "A. Alpha", rankings={1: 310, 2: 420})
        self.assertTrue(mapping.updates["scan_is_qualification"])


if __name__ == "__main__":
    unittest.main()


def test_one_break_at_one_game_can_never_trade_even_with_40_love_confirmation() -> None:
    match = eligible_match()
    match.break_lead = 1
    match.backed_player_games_in_set = 1
    match.opponent_games_in_set = 0
    match.current_set_breaks_suffered = 0
    match.serving = True
    match.current_game_score = "40-0"
    match.current_service_game_reached_40_0 = True
    decision = evaluate_match(match)
    assert decision.status == "NO TRADE"
    assert any("at least 4 games" in concern for concern in decision.concerns)
