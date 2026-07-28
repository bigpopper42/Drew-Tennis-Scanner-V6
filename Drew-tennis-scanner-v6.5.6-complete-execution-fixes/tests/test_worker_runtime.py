from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from scanner.decision import evaluate_match
from scanner.live_mapping import LiveMappingResult
from scanner.live_scan import PlayerScanResult
from scanner.models import MatchInput
from scanner.worker_runtime import RailwayShadowWorker, WorkerConfig


class FakeSnapshot:
    def __init__(self, events):
        self.events = events
        self.warnings = []
        self.fixture_events = []

    def summary(self):
        return {
            "events": len(self.events),
            "livescore_count": len(self.events),
            "fixtures_live_count": 0,
            "duplicates_removed": 0,
            "duration_seconds": 0.01,
            "timezone": "America/Phoenix",
            "warnings": [],
        }


class WorkerConfigTests(unittest.TestCase):
    def test_secret_key_is_preferred_and_public_summary_hides_secrets(self):
        env = {
            "API_TENNIS_KEY": "api-key",
            "SUPABASE_URL": "https://example.supabase.co",
            "SUPABASE_SECRET_KEY": "sb_secret_test",
            "SUPABASE_SERVICE_ROLE_KEY": "legacy-key",
        }
        with patch.dict(os.environ, env, clear=True):
            config = WorkerConfig.from_env()
        self.assertEqual(config.supabase_key, "sb_secret_test")
        summary = config.public_summary()
        self.assertNotIn("api_tennis_key", summary)
        self.assertNotIn("supabase_key", summary)

    def test_dry_run_does_not_require_supabase(self):
        with patch.dict(
            os.environ,
            {"API_TENNIS_KEY": "api-key", "DRY_RUN": "true"},
            clear=True,
        ):
            config = WorkerConfig.from_env()
        self.assertTrue(config.dry_run)

    def test_save_all_scans_environment_variable_is_honored(self):
        with patch.dict(
            os.environ,
            {
                "API_TENNIS_KEY": "api-key",
                "DRY_RUN": "true",
                "SAVE_ALL_SCANS": "true",
            },
            clear=True,
        ):
            config = WorkerConfig.from_env()
        self.assertTrue(config.save_all_scans)
        self.assertEqual(config.public_summary()["storage_mode"], "all_player_evaluations")

    def test_legacy_bankroll_environment_value_cannot_override_locked_twenty_percent(self):
        with patch.dict(
            os.environ,
            {
                "API_TENNIS_KEY": "api-key",
                "DRY_RUN": "true",
                "EXECUTION_BANKROLL_PCT": "10",
            },
            clear=True,
        ):
            config = WorkerConfig.from_env()
        self.assertEqual(config.execution_bankroll_pct, 20.0)
        self.assertEqual(config.public_summary()["execution_bankroll_pct"], 20.0)

    def test_legacy_maximum_order_environment_value_is_ignored(self):
        with patch.dict(
            os.environ,
            {
                "API_TENNIS_KEY": "api-key",
                "DRY_RUN": "true",
                "EXECUTION_MAX_ORDER_USD": "1",
            },
            clear=True,
        ):
            config = WorkerConfig.from_env()
        self.assertFalse(hasattr(config, "execution_maximum_order_usd"))
        self.assertIsNone(config.public_summary()["execution_maximum_order_usd"])
        self.assertTrue(config.public_summary()["execution_same_market_upgrades"])


class WorkerLogicTests(unittest.TestCase):
    def setUp(self):
        self.config = WorkerConfig(
            api_tennis_key="test",
            supabase_url="",
            supabase_key="",
            dry_run=True,
            worker_id="test-worker",
            minimum_market_confidence=80,
        )
        self.worker = RailwayShadowWorker(self.config)

    def test_market_candidate_must_be_open_match_winner_and_confident(self):
        rows = [
            {
                "market_slug": "wrong",
                "match_winner_market": False,
                "api_match_confidence": 99,
            },
            {
                "market_slug": "closed",
                "match_winner_market": True,
                "api_match_confidence": 99,
                "closed": True,
            },
            {
                "market_slug": "safe",
                "match_winner_market": True,
                "api_match_confidence": 91,
                "active": True,
                "closed": False,
            },
        ]
        selected = self.worker._select_market_candidate(rows)
        self.assertEqual(selected["market_slug"], "safe")

    def test_dedupe_key_ignores_informational_price_but_not_key_order(self):
        base = {
            "event_key": "1",
            "player": "A",
            "event_status": "Set 2",
            "event_final_result": "1 - 0",
            "event_game_result": "30 - 15",
            "event_serve": "First Player",
            "event_state": {"scores": [{"score_first": "4", "score_second": "2"}]},
            "market_slug": "a-vs-b",
            "market_side": "Long / YES",
            "market_price_cents": 98.0,
            "decision_status": "TRADE",
            "stability_score": 90.0,
        }
        reordered = dict(reversed(list(base.items())))
        self.assertEqual(self.worker._dedupe_key(base), self.worker._dedupe_key(reordered))
        changed = dict(base, market_price_cents=99.0)
        self.assertEqual(self.worker._dedupe_key(base), self.worker._dedupe_key(changed))
        changed_state = dict(base, event_game_result="40 - 15")
        self.assertNotEqual(
            self.worker._dedupe_key(base), self.worker._dedupe_key(changed_state)
        )

    def test_worker_defaults_to_qualified_trade_only_storage(self):
        self.assertFalse(self.config.save_all_scans)

    def test_save_all_mode_persists_no_trade_rows(self):
        all_config = WorkerConfig(
            api_tennis_key="test",
            supabase_url="",
            supabase_key="",
            dry_run=True,
            worker_id="test-worker",
            save_all_scans=True,
        )
        all_worker = RailwayShadowWorker(all_config)
        rows = [
            {"decision_status": "TRADE"},
            {"decision_status": "NO TRADE"},
        ]
        self.assertEqual(all_worker._persist_records(rows).inserted, 2)
        self.assertEqual(self.worker._persist_records(rows).inserted, 1)

    def test_no_trade_record_contains_exact_diagnostics_and_is_not_open(self):
        all_config = WorkerConfig(
            api_tennis_key="test",
            supabase_url="",
            supabase_key="",
            dry_run=True,
            worker_id="test-worker",
            save_all_scans=True,
        )
        worker = RailwayShadowWorker(all_config)
        match = MatchInput(
            player="Player A",
            opponent="Player B",
            tournament="Test ATP",
            league="ATP",
            competition_group="ATP Tour",
            event_key="event-1",
            match_closing_set=False,
            tiebreak=False,
            break_lead=0,
            serving=True,
            current_set_breaks_suffered=0,
            effective_service_points_won_pct=65.0,
            backed_player_games_in_set=2,
            opponent_games_in_set=2,
        )
        decision = evaluate_match(match)
        mapping = LiveMappingResult(
            updates={},
            api_fields=[],
            calculated_fields=[],
            manual_fields=[],
            warnings=[],
        )
        result = PlayerScanResult(
            player=match.player,
            match=match,
            decision=decision,
            mapping=mapping,
        )
        record = worker._build_scan_record(
            {
                "event_key": "event-1",
                "event_first_player": "Player A",
                "event_second_player": "Player B",
            },
            result,
            "00000000-0000-0000-0000-000000000001",
            "2026-07-24T21:00:00+00:00",
            market_row=None,
            market_side=None,
            market_price=0.0,
            extra_errors=[],
        )
        self.assertEqual(record["decision_status"], "NO TRADE")
        self.assertIn("Current set is not match-closing", record["decision_reason"])
        self.assertIn("Backed player is not ahead by a break", record["decision_reason"])
        self.assertEqual(record["paper_trade_status"], "NOT_ENTERED")
        self.assertIsNone(record["paper_entry_price_cents"])
        self.assertFalse(record["alert_eligible"])
        diagnostics = record["match_snapshot"]["decision_diagnostics"]
        self.assertEqual(diagnostics["status"], "NO TRADE")
        self.assertTrue(diagnostics["blocking_rules"])

    def test_winner_resolution_from_completed_fixture(self):
        event = {
            "event_first_player": "A",
            "event_second_player": "B",
            "event_final_result": "2 - 1",
        }
        self.assertEqual(self.worker._fixture_winner(event)[0], "A")


if __name__ == "__main__":
    unittest.main()
