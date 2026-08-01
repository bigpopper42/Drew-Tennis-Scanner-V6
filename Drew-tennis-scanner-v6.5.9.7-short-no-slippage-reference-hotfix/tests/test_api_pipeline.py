import unittest
from unittest.mock import patch

from scanner.api_tennis import get_live_events, get_live_snapshot
from scanner.event_pipeline import build_pipeline, event_competition_group, is_itf_m15_mens_singles, is_singles_event


def event(key, event_type="ATP Singles", tournament="ATP 250 Phoenix Men", live="1"):
    return {
        "event_key": str(key),
        "event_first_player": "A. Alpha",
        "event_second_player": "B. Beta",
        "event_type_type": event_type,
        "tournament_name": tournament,
        "event_status": "Set 2",
        "event_live": live,
        "event_final_result": "1 - 0",
        "event_game_result": "30 - 15",
        "event_serve": "First Player",
        "scores": [{"score_set": "2", "score_first": "3", "score_second": "1"}],
    }


class ResponseShapeTests(unittest.TestCase):
    @patch("scanner.api_tennis._request")
    def test_dictionary_keyed_livescore_response_is_not_dropped(self, request):
        request.return_value = {"101": event(101), "102": event(102)}
        rows = get_live_events("key")
        self.assertEqual({row["event_key"] for row in rows}, {"101", "102"})


class SnapshotTests(unittest.TestCase):
    @patch("scanner.api_tennis.get_fixtures")
    @patch("scanner.api_tennis.get_live_events")
    def test_livescore_and_live_fixture_fallback_are_merged(self, live, fixtures):
        live.return_value = [event(1), event(2)]
        richer_duplicate = event(2)
        richer_duplicate["statistics"] = [{"player_key": 1}]
        fixtures.return_value = [richer_duplicate, event(3), event(4, live="0")]
        snapshot = get_live_snapshot("key", local_date="2026-07-21")
        self.assertEqual(len(snapshot.events), 3)
        self.assertEqual(snapshot.livescore_count, 2)
        self.assertEqual(snapshot.fixtures_live_count, 2)
        self.assertEqual(snapshot.duplicates_removed, 1)
        merged = next(row for row in snapshot.events if row["event_key"] == "2")
        self.assertTrue(merged.get("statistics"))

    @patch("scanner.api_tennis.get_fixtures")
    @patch("scanner.api_tennis.get_live_events")
    def test_fixture_failure_never_blocks_livescore(self, live, fixtures):
        live.return_value = [event(1)]
        fixtures.side_effect = RuntimeError("fixture outage")
        snapshot = get_live_snapshot("key", local_date="2026-07-21")
        self.assertEqual(len(snapshot.events), 1)
        self.assertEqual(len(snapshot.warnings), 1)


class PipelineTests(unittest.TestCase):
    def test_itf_m15_mens_singles_is_recognized_but_not_supported_in_v6(self):
        row = event(1, event_type="ITF Men Singles", tournament="ITF M15 Monastir Men")
        self.assertTrue(is_singles_event(row))
        self.assertEqual(event_competition_group(row), "ITF")
        self.assertTrue(is_itf_m15_mens_singles(row))
        self.assertEqual(len(build_pipeline([row]).supported_events), 0)

    def test_m15_tournament_fallback_when_type_omits_singles(self):
        row = event(1, event_type="Men", tournament="ITF M15 Monastir Men")
        self.assertTrue(is_singles_event(row))
        self.assertTrue(is_itf_m15_mens_singles(row))

    def test_doubles_are_excluded_with_reason_not_silently_dropped(self):
        singles = event(1)
        doubles = event(2, event_type="ITF Men Doubles")
        doubles["event_first_player"] = "A/B"
        result = build_pipeline([singles, doubles])
        self.assertEqual(len(result.all_events), 2)
        self.assertEqual(len(result.rows), 2)
        self.assertEqual(len(result.supported_events), 1)
        excluded = next(row for row in result.rows if not row.included)
        self.assertIn("singles", excluded.reason.lower())

    def test_missing_stats_and_point_by_point_do_not_exclude_match(self):
        row = event(1)
        result = build_pipeline([row])
        self.assertEqual(len(result.supported_events), 1)
        self.assertEqual(result.counts["missing_pointbypoint_but_included"], 1)
        self.assertEqual(result.counts["missing_statistics_but_included"], 1)

    def test_large_live_list_is_not_truncated(self):
        events = [event(index) for index in range(1, 151)]
        result = build_pipeline(events)
        self.assertEqual(len(result.all_events), 150)
        self.assertEqual(len(result.supported_events), 150)
        self.assertEqual(len(result.rows), 150)


if __name__ == "__main__":
    unittest.main()
