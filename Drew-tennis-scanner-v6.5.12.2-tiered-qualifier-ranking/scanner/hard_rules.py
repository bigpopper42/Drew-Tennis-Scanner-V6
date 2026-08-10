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

    # This confirmation helper retains the service/point-score confirmation.
    # Version 6.5.12.2 applies a separate minimum-games hard gate before this result
    # can make a one-break lead eligible.
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

    # Version 6.5.12.2 qualification-volatility gate. Qualifiers use a tiered
    # ranking rule that preserves volume while demanding a larger ranking gap
    # when the backed player is outside the top 150:
    #   backed 1-150   -> opponent rank does not matter;
    #   backed 151-200 -> opponent must be ATP #450 or worse;
    #   backed 201-250 -> opponent must be ATP #750 or worse;
    #   backed 251+    -> blocked.
    # Missing backed-player rank always blocks. Opponent rank is required only
    # for the 151-250 tiers. Main-draw Tour/Challenger matches keep the existing
    # ranking treatment.
    if match.is_qualification:
        if match.ranking is None:
            failed.append(
                "Qualification match requires a verified ATP ranking for the backed player"
            )
        elif match.ranking <= 150:
            opponent_text = (
                f"ATP #{match.opponent_ranking}" if match.opponent_ranking is not None else "opponent rank unavailable"
            )
            passed.append(
                f"Qualification ranking gate passed: backed ATP #{match.ranking} (top-150 tier) vs {opponent_text}"
            )
        elif match.ranking <= 200:
            if match.opponent_ranking is None:
                failed.append(
                    "Qualification match with backed ATP rank 151-200 requires a verified opponent ranking of 450 or worse"
                )
            elif match.opponent_ranking < 450:
                failed.append(
                    f"Qualification match blocked: backed ATP #{match.ranking} in the 151-200 tier requires opponent ATP #450 or worse (opponent is #{match.opponent_ranking})"
                )
            else:
                passed.append(
                    f"Qualification ranking gate passed: backed ATP #{match.ranking} vs opponent ATP #{match.opponent_ranking} (requires #450 or worse)"
                )
        elif match.ranking <= 250:
            if match.opponent_ranking is None:
                failed.append(
                    "Qualification match with backed ATP rank 201-250 requires a verified opponent ranking of 750 or worse"
                )
            elif match.opponent_ranking < 750:
                failed.append(
                    f"Qualification match blocked: backed ATP #{match.ranking} in the 201-250 tier requires opponent ATP #750 or worse (opponent is #{match.opponent_ranking})"
                )
            else:
                passed.append(
                    f"Qualification ranking gate passed: backed ATP #{match.ranking} vs opponent ATP #{match.opponent_ranking} (requires #750 or worse)"
                )
        else:
            failed.append(
                "Qualification match is blocked when the backed player is ranked ATP #251 or worse"
            )
    else:
        passed.append("Main-draw/non-qualification match passed qualification-volatility gate")

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

    # One-break maturity hard gate (Version 6.5.12.2): early breaks cannot become
    # tradeable merely because they were consolidated. If the backed player has
    # not been broken in the current set, they must first win at least four games
    # in that set. If they have been broken once, they must first win at least five
    # games. The existing consolidation/point-score confirmation still applies
    # after this minimum-game gate. Two-break leads remain immediately mature.
    if match.break_lead == 1:
        games = match.backed_player_games_in_set
        if games is None:
            unknown.append("Current-set games won is unavailable for one-break maturity rule")
        elif current_breaks is None:
            if not fallback:
                unknown.append("Current-set break history is unavailable for one-break maturity rule")
        else:
            minimum_games = 5 if current_breaks >= 1 else 4
            if games < minimum_games:
                failed.append(
                    f"One-break lead requires at least {minimum_games} games won in the current set "
                    f"when the backed player has been broken {current_breaks} time(s)"
                )
            else:
                passed.append(
                    f"One-break maturity gate passed: {games} current-set games won "
                    f"with {current_breaks} break(s) suffered"
                )

        if match.backed_player_games_in_set is None or match.opponent_games_in_set is None:
            unknown.append("Current-set game score is unavailable for one-break confirmation")
        else:
            games = int(match.backed_player_games_in_set or 0)
            fresh_break = match.last_completed_game_was_break_by_backed is True

            # Version 6.5.12.2 closes the late-set consolidation loophole. If the
            # backed player has JUST broken to reach four or five games, the
            # lead is not considered consolidated merely because the minimum-
            # games maturity gate is already satisfied. They must establish a
            # dominant score in the immediately following service game.
            if fresh_break and games in {4, 5}:
                if match.serving is not True:
                    failed.append(
                        "Fresh one-break lead cannot qualify until the backed player begins the consolidation service game"
                    )
                elif games == 4:
                    if match.current_service_game_reached_40_0 is True:
                        passed.append(
                            "Fresh break at four games consolidated by reaching 40-0 while serving for game five"
                        )
                    else:
                        failed.append(
                            "Fresh break at four games requires reaching 40-0 while serving for game five"
                        )
                else:  # games == 5
                    if match.current_service_game_reached_30_0 is True:
                        passed.append(
                            "Fresh break at five games consolidated by reaching 30-0 while serving for game six"
                        )
                    else:
                        failed.append(
                            "Fresh break at five games requires reaching 30-0 while serving for game six"
                        )
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
