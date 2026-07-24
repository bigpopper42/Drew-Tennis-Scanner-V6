from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .models import MatchInput


@dataclass
class HardRuleResult:
    status: str
    passed: List[str]
    failed: List[str]
    waiting: List[str]
    unknown: List[str]
    limited_fallback: bool = False


def _score(value: str) -> str:
    return str(value or "0-0").strip().replace("–", "-").replace(" ", "")


def qualifies_for_missing_service_fallback(match: MatchInput) -> bool:
    """The only Version 6.0 missing-service exception.

    It is intentionally narrow: the backed player must lead by at least two
    breaks and be the clearly higher-ranked player in one of the two locked
    disparity bands. The recommendation is capped at 3% by decision.py.
    """

    player_rank = match.ranking
    opponent_rank = match.opponent_ranking
    if not player_rank or not opponent_rank or (match.break_lead or 0) < 2:
        return False
    return (player_rank <= 50 and opponent_rank >= 300) or (
        player_rank <= 100 and opponent_rank >= 500
    )


def _effective_service(match: MatchInput) -> Optional[float]:
    if match.effective_service_points_won_pct is not None:
        return float(match.effective_service_points_won_pct)
    if match.service_points_won_pct is not None:
        return float(match.service_points_won_pct)
    return None


def _one_break_confirmed(match: MatchInput, service_pct: Optional[float]) -> bool:
    games = int(match.backed_player_games_in_set or 0)
    opponent_games = int(match.opponent_games_in_set or 0)
    score = _score(match.current_game_score)
    serving = match.serving is True
    strong_service = service_pct is not None and service_pct >= 70.0

    # A completed consolidation hold creates at least a two-game score margin.
    if games - opponent_games >= 2:
        return True

    # Early one-break leads (1-0, 2-1, 3-2) normally need the hold. The locked
    # exception is strong service plus a 30-0-or-better point position.
    if games <= 3:
        return serving and strong_service and score in {"30-0", "40-0", "40-15"}

    # Late one-break leads may qualify inside the service game.
    if not serving:
        return False
    if strong_service:
        return score in {"30-0", "40-0", "40-15"}

    # Below 70%, use the safer confirmation selected in the final audit:
    # 40-0, or any actual match-point score while serving for the match.
    if score == "40-0":
        return True
    if match.serving_for_match and score in {"40-15", "40-30", "Ad-In"}:
        return True
    return False


def evaluate_hard_rules(match: MatchInput) -> HardRuleResult:
    passed: List[str] = []
    failed: List[str] = []
    unknown: List[str] = []
    waiting: List[str] = []  # kept for backward-compatible result shape; V6 never emits WAIT.

    # ATP-only strategy. Unknown is allowed for manual test entries, but WTA,
    # ITF, and other lower-level groups are rejected by both pipeline and rules.
    league = str(match.league or "Unknown").upper()
    group = str(match.competition_group or "Unknown").lower()
    if league == "WTA" or group in {"itf", "other"}:
        failed.append("Version 6.0 scans ATP Tour and Challenger singles only")
    else:
        passed.append("ATP-only competition scope passed")

    if match.match_closing_set is True:
        passed.append("Current set is match-closing")
    elif match.match_closing_set is False:
        failed.append("Current set is not match-closing")
    else:
        unknown.append("Match-closing set could not be verified")

    if match.tiebreak is True:
        failed.append("Tiebreak entries are never eligible")
    elif match.tiebreak is False:
        passed.append("Current set is not a tiebreak")
    else:
        unknown.append("Tiebreak state is unavailable")

    if match.break_lead is None:
        unknown.append("Current break lead is unavailable")
    elif match.break_lead < 1:
        failed.append("Backed player is not ahead by a break")
    else:
        passed.append(f"Backed player leads by {match.break_lead} break(s)")

    fallback = qualifies_for_missing_service_fallback(match)

    current_breaks = match.current_set_breaks_suffered
    if current_breaks is None:
        if fallback:
            passed.append("Current-set break history is unavailable under the limited fallback")
        else:
            unknown.append("Current-set break history is unavailable")
    elif current_breaks >= 2:
        failed.append("Backed player was broken at least twice in the current set")
    else:
        passed.append("Current-set break-volatility rule passed")

    service_pct = _effective_service(match)
    if service_pct is None or service_pct <= 0:
        if fallback:
            passed.append("Limited missing-service fallback passed")
        else:
            failed.append("Service points won is unavailable and the limited fallback does not apply")
    elif service_pct < 61.0:
        failed.append("Service points won is below the 61% hard minimum")
    else:
        passed.append(f"Effective service points won is {service_pct:.1f}%")

    # Two-break leads are immediately mature. One-break leads require the exact
    # consolidation/point-score confirmation locked in the final questionnaire.
    if match.break_lead == 1:
        if match.backed_player_games_in_set is None or match.opponent_games_in_set is None:
            unknown.append("Current-set game score is unavailable for one-break confirmation")
        elif _one_break_confirmed(match, service_pct):
            passed.append("One-break lead has the required consolidation or point-score confirmation")
        else:
            failed.append("One-break lead has not reached the required confirmation")
    elif match.break_lead is not None and match.break_lead >= 2:
        passed.append("Two-break lead is immediately mature")

    status = "ELIGIBLE" if not failed and not unknown else "NO TRADE"
    return HardRuleResult(
        status=status,
        passed=passed,
        failed=failed,
        waiting=waiting,
        unknown=unknown,
        limited_fallback=fallback and service_pct in (None, 0),
    )
