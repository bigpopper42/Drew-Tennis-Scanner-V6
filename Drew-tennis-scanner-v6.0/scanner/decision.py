from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List

from .hard_rules import evaluate_hard_rules
from .models import MatchInput
from .scoring import calculate_stability_result, position_size


@dataclass
class Decision:
    status: str
    score: float
    minimum_score: float
    stake_pct: float
    stake_amount: float
    passed: List[str]
    concerns: List[str]
    score_parts: Dict[str, float]
    factor_availability: Dict[str, bool]
    reason: str
    data_completeness_pct: float
    core_completeness_pct: float
    scoring_completeness_pct: float


def evaluate_match(match: MatchInput) -> Decision:
    """Evaluate the final Version 6.0 decision tree.

    Polymarket price is intentionally absent from every qualification and sizing
    branch. It remains available on MatchInput for display and trade recording.
    """

    hard = evaluate_hard_rules(match)
    stability = calculate_stability_result(match)
    concerns = list(
        dict.fromkeys(
            hard.failed
            + hard.unknown
            + list(match.mapping_warnings or [])
        )
    )

    common = dict(
        score=stability.score,
        minimum_score=75.0,
        stake_pct=0.0,
        stake_amount=0.0,
        passed=hard.passed,
        concerns=concerns,
        score_parts=stability.parts,
        factor_availability=stability.available_factors,
        data_completeness_pct=float(match.data_completeness_pct or 0.0),
        core_completeness_pct=float(match.core_completeness_pct or 0.0),
        scoring_completeness_pct=stability.scoring_completeness_pct,
    )

    if hard.status != "ELIGIBLE":
        return Decision(
            status="NO TRADE",
            reason="One or more final decision-tree qualification rules are not satisfied.",
            **common,
        )

    if hard.limited_fallback:
        pct = 0.03
        common["stake_pct"] = pct
        common["stake_amount"] = round(max(0.0, float(match.bankroll or 0.0)) * pct, 2)
        return Decision(
            status="TRADE",
            reason=(
                "Limited 3% missing-service fallback: two-break lead and the locked "
                "ranking disparity rule passed."
            ),
            **common,
        )

    pct = position_size(stability.score)
    if pct <= 0:
        return Decision(
            status="NO TRADE",
            reason=f"Stability Score {stability.score:.1f} is below the 75-point minimum.",
            **common,
        )

    common["stake_pct"] = pct
    common["stake_amount"] = round(max(0.0, float(match.bankroll or 0.0)) * pct, 2)
    return Decision(
        status="TRADE",
        reason="All Version 6.0 qualification rules passed.",
        **common,
    )
