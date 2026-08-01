from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

from .models import MatchInput


@dataclass
class StabilityResult:
    score: float
    parts: Dict[str, float]
    raw_parts: Dict[str, float]
    available_factors: Dict[str, bool]
    scoring_completeness_pct: float


def _number(value: Optional[float]) -> Optional[float]:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def _weighted(current: Optional[float], full: Optional[float], *, deciding_set: bool) -> Optional[float]:
    current_value = _number(current)
    full_value = _number(full)
    if current_value is not None and full_value is not None:
        # Final audit: deciding set = 65% current / 35% full.
        # Other match-closing sets = 30% current / 70% full.
        current_weight = 0.65 if deciding_set else 0.30
        return round(current_weight * current_value + (1.0 - current_weight) * full_value, 2)
    return current_value if current_value is not None else full_value


def effective_service_pct(match: MatchInput) -> Optional[float]:
    if match.effective_service_points_won_pct is not None:
        return _number(match.effective_service_points_won_pct)
    return _weighted(
        match.current_set_service_points_won_pct,
        match.service_points_won_pct,
        deciding_set=bool(match.deciding_set),
    )


def effective_first_serve_points_pct(match: MatchInput) -> Optional[float]:
    return _weighted(
        match.current_set_first_serve_points_won_pct,
        match.first_serve_points_won_pct,
        deciding_set=bool(match.deciding_set),
    )


def effective_first_serve_in_pct(match: MatchInput) -> Optional[float]:
    return _weighted(
        match.current_set_first_serve_in_pct,
        match.first_serve_in_pct,
        deciding_set=bool(match.deciding_set),
    )


def effective_opponent_service_pct(match: MatchInput) -> Optional[float]:
    return _weighted(
        match.opponent_current_set_service_points_won_pct,
        match.opponent_service_points_won_pct,
        deciding_set=bool(match.deciding_set),
    )


def _service_points(value: Optional[float]) -> float:
    """Continuous 13–31 point scale; 61% remains the hard floor."""
    if value is None or value < 61.0:
        return 0.0
    if value <= 70.0:
        return round(13.0 + (value - 61.0) * (13.0 / 9.0), 2)
    return round(min(31.0, 26.0 + (value - 70.0)), 2)


def _first_serve_points(value: Optional[float]) -> float:
    if value is None:
        return 0.0
    if value < 60.0:
        return 0.0
    if value >= 80.0:
        return 10.0
    # Continuous from 2 points at 60% to 10 points at 80%.
    return round(2.0 + (value - 60.0) * 0.4, 2)


def _first_serve_in(value: Optional[float]) -> float:
    if value is None or value < 55.0:
        return 0.0
    if value >= 70.0:
        return 3.0
    return round((value - 55.0) * (3.0 / 15.0), 2)


def _double_fault_stability(value: Optional[float]) -> float:
    if value is None:
        return 0.0
    if value <= 0.15:
        return 2.0
    if value <= 0.30:
        return 1.5
    if value <= 0.45:
        return 0.5
    return 0.0


def _match_state(match: MatchInput) -> float:
    lead = int(match.break_lead or 0)
    serving = match.serving is True
    if lead >= 2 and serving:
        base = 20.0
    elif lead >= 2:
        base = 17.0
    elif lead == 1 and serving:
        base = 14.0
    elif lead == 1:
        base = 11.0
    else:
        return 0.0

    games = int(match.backed_player_games_in_set or 0)
    proximity = 4.0 if games >= 5 else 3.0 if games == 4 else 1.0 if games == 3 else 0.0
    serve_out = 5.0 if match.serving_for_match else 0.0
    return min(25.0, base + proximity + serve_out)


def _break_point_dominance(created: Optional[int], faced: Optional[int]) -> float:
    """Reward dominance without separately penalizing break points faced.

    This implements the user's no-double-counting correction: break points faced
    are not their own negative factor. Only a positive creation differential is
    rewarded, with the strongest bonus when the opponent has created none.
    """
    if created is None or faced is None:
        return 0.0
    created_i, faced_i = max(0, int(created)), max(0, int(faced))
    difference = created_i - faced_i
    if created_i >= 4 and faced_i == 0:
        return 8.0
    if difference >= 4:
        return 7.0
    if difference >= 2:
        return 5.0
    if difference >= 1:
        return 3.0
    if created_i > 0 and difference == 0:
        return 1.0
    return 0.0


def _opponent_service_pressure(value: Optional[float]) -> float:
    if value is None:
        return 0.0
    if value < 45.0:
        return 5.0
    if value < 50.0:
        return 4.0
    if value < 55.0:
        return 3.0
    if value < 60.0:
        return 1.0
    return 0.0


def ranking_adjustment(match: MatchInput) -> float:
    player_rank, opponent_rank = match.ranking, match.opponent_ranking
    if not player_rank or not opponent_rank:
        return 0.0
    major_advantage = (player_rank <= 50 and opponent_rank >= 300) or (
        player_rank <= 100 and opponent_rank >= 500
    )
    major_disadvantage = (opponent_rank <= 50 and player_rank >= 300) or (
        opponent_rank <= 100 and player_rank >= 500
    )
    if major_advantage:
        return 3.0
    if major_disadvantage:
        return -2.0
    return 0.0


def calculate_stability_result(match: MatchInput) -> StabilityResult:
    service = effective_service_pct(match)
    first_serve_points = effective_first_serve_points_pct(match)
    first_serve_in = effective_first_serve_in_pct(match)
    opponent_service = effective_opponent_service_pct(match)

    current_breaks = match.current_set_breaks_suffered
    service_protection = 10.0 if current_breaks == 0 else 5.0 if current_breaks == 1 else 0.0

    raw: Dict[str, float] = {
        "Effective service points won": _service_points(service),
        "First-serve points won": _first_serve_points(first_serve_points),
        "Current-set service protection": service_protection,
        "Match-state strength": _match_state(match),
        "Break-point dominance": _break_point_dominance(
            match.break_points_created, match.break_points_faced
        ),
        "Opponent service pressure": _opponent_service_pressure(opponent_service),
        "First-serve percentage": _first_serve_in(first_serve_in),
        "Double-fault stability": _double_fault_stability(
            match.double_faults_per_service_game
        ),
        "Straight-set closing bonus": 3.0 if match.straight_set_closing else 0.0,
        "Ranking adjustment": ranking_adjustment(match),
    }

    # Positive maxima total exactly 100. The locked -2 ranking disadvantage can
    # reduce the total but cannot create negative scores.
    score = round(max(0.0, min(100.0, sum(raw.values()))), 2)
    available: Dict[str, bool] = {
        "Effective service points won": service is not None,
        "First-serve points won": first_serve_points is not None,
        "Current-set service protection": current_breaks is not None,
        "Match-state strength": match.break_lead is not None and match.serving is not None,
        "Break-point dominance": match.break_points_created is not None and match.break_points_faced is not None,
        "Opponent service pressure": opponent_service is not None,
        "First-serve percentage": first_serve_in is not None,
        "Double-fault stability": match.double_faults_per_service_game is not None,
        "Straight-set closing bonus": True,
        "Ranking adjustment": match.ranking is not None and match.opponent_ranking is not None,
    }
    completeness = round(
        sum(1 for value in available.values() if value) / len(available) * 100.0,
        1,
    )
    return StabilityResult(
        score=score,
        parts=dict(raw),
        raw_parts=dict(raw),
        available_factors=available,
        scoring_completeness_pct=completeness,
    )


def calculate_stability_score(match: MatchInput):
    result = calculate_stability_result(match)
    return result.score, result.parts


def price_minimum_score(_price: float) -> float:
    """Backward-compatible API: price no longer changes the threshold."""
    return 75.0


def position_size(score: float) -> float:
    # Final audit choice B.
    return 0.07 if score >= 93.0 else 0.05 if score >= 85.0 else 0.03 if score >= 75.0 else 0.0
