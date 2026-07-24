from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest.mock import patch

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

    def test_worker_defaults_to_qualified_trade_only_storage(self):
        self.assertFalse(self.config.save_all_scans)

    def test_winner_resolution_from_completed_fixture(self):
        event = {
            "event_first_player": "A",
            "event_second_player": "B",
            "event_final_result": "2 - 1",
        }
        self.assertEqual(self.worker._fixture_winner(event)[0], "A")


if __name__ == "__main__":
    unittest.main()
