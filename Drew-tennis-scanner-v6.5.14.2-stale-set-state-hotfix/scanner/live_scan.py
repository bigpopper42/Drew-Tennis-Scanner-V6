from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional

from .decision import Decision, evaluate_match
from .live_mapping import LiveMappingResult, build_live_scanner_mapping
from .models import MatchInput


@dataclass
class PlayerScanResult:
    player: str
    match: MatchInput
    decision: Decision
    mapping: LiveMappingResult
    error: Optional[str] = None


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return default if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return default


def _as_optional_float(value: Any, *, allow_zero: bool = False) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if allow_zero:
        return number if number >= 0 else None
    return number if number > 0 else None


def _as_optional_int(value: Any, *, allow_zero: bool = True) -> Optional[int]:
    try:
        if value in (None, ""):
            return None
        number = int(float(value))
        return number if allow_zero or number > 0 else None
    except (TypeError, ValueError):
        return None


def _breaks_by_set(value: Any) -> List[int]:
    output: List[int] = []
    for token in str(value or "").split(","):
        try:
            output.append(max(0, int(token.strip())))
        except ValueError:
            continue
    return output


def _lookup_price(price_by_player: Mapping[str, Any], player: str) -> float:
    if player in price_by_player:
        return max(0.0, _as_float(price_by_player[player]))
    normalized = player.strip().casefold()
    for key, value in price_by_player.items():
        if str(key).strip().casefold() == normalized:
            return max(0.0, _as_float(value))
    return 0.0


def match_from_mapping(
    mapping: LiveMappingResult,
    *,
    market_price_cents: float = 0.0,
    market_price_timestamp: Optional[str] = None,
    market_volume: Optional[float] = None,
    market_liquidity: Optional[float] = None,
    bankroll: float = 0.0,
) -> MatchInput:
    u = mapping.updates

    def available(name: str) -> bool:
        status = mapping.field_status.get(name)
        return bool(status and status.available)

    def optional_float(update_key: str, field_name: str, *, allow_zero: bool = False) -> Optional[float]:
        return _as_optional_float(u.get(update_key), allow_zero=allow_zero) if available(field_name) else None

    def optional_int(update_key: str, field_name: str, *, allow_zero: bool = True) -> Optional[int]:
        return _as_optional_int(u.get(update_key), allow_zero=allow_zero) if available(field_name) else None

    return MatchInput(
        player=str(u.get("scan_player") or "Unknown player"),
        opponent=str(u.get("scan_opponent") or "Unknown opponent"),
        tournament=str(u.get("scan_tournament") or "Unknown tournament"),
        surface="Unknown",
        market_price_cents=max(0.0, _as_float(market_price_cents)),
        market_price_timestamp=market_price_timestamp,
        market_volume=_as_optional_float(market_volume, allow_zero=True),
        market_liquidity=_as_optional_float(market_liquidity, allow_zero=True),
        bankroll=max(0.0, _as_float(bankroll)),
        league=str(u.get("scan_league") or "Unknown"),
        competition_group=str(u.get("scan_competition_group") or "Unknown"),
        is_qualification=bool(u.get("scan_is_qualification")),
        best_of_sets=max(3, int(_as_float(u.get("scan_best_of_sets"), 3))),
        current_set_number=optional_int("scan_current_set", "current_set"),
        match_closing_set=(bool(u.get("scan_match_closing_set")) if available("match_closing_set") else None),
        straight_set_closing=bool(u.get("scan_straight_set_closing")),
        deciding_set=bool(u.get("scan_deciding_set")),
        break_lead=optional_int("scan_break_lead", "break_lead"),
        serving=(bool(u.get("scan_serving")) if available("serving") else None),
        serving_for_match=bool(u.get("scan_serving_for_match")),
        tiebreak=(bool(u.get("scan_tiebreak")) if available("tiebreak") else None),
        backed_player_games_in_set=optional_int("scan_games_in_set", "games_in_set"),
        opponent_games_in_set=optional_int("scan_opponent_games_in_set", "opponent_games_in_set"),
        current_game_score=str(u.get("scan_game_score") or "0-0"),
        completed_sets=_as_optional_int(u.get("scan_completed_sets")),
        last_completed_game_was_break_by_backed=(
            bool(u.get("scan_last_game_break_by_backed"))
            if available("last_completed_game_was_break_by_backed")
            else None
        ),
        current_service_game_reached_30_0=(
            bool(u.get("scan_current_service_reached_30_0"))
            if available("current_service_game_reached_30_0")
            else None
        ),
        current_service_game_reached_40_0=(
            bool(u.get("scan_current_service_reached_40_0"))
            if available("current_service_game_reached_40_0")
            else None
        ),
        breaks_suffered_by_set=_breaks_by_set(u.get("scan_breaks_by_set")),
        breaks_suffered_total=optional_int("scan_breaks_total", "breaks_suffered_total"),
        current_set_breaks_suffered=optional_int(
            "scan_current_set_breaks", "current_set_breaks_suffered"
        ),
        service_points_won_pct=optional_float(
            "scan_service_points", "service_points_won_pct"
        ),
        current_set_service_points_won_pct=optional_float(
            "scan_current_set_service_points", "current_set_service_points_won_pct"
        ),
        effective_service_points_won_pct=optional_float(
            "scan_effective_service_points", "effective_service_points_won_pct"
        ),
        opponent_service_points_won_pct=optional_float(
            "scan_opponent_service_points", "opponent_service_points_won_pct"
        ),
        opponent_current_set_service_points_won_pct=optional_float(
            "scan_opponent_current_set_service_points",
            "opponent_current_set_service_points_won_pct",
        ),
        first_serve_points_won_pct=optional_float(
            "scan_first_serve_points", "first_serve_points_won_pct"
        ),
        current_set_first_serve_points_won_pct=optional_float(
            "scan_current_set_first_serve_points",
            "current_set_first_serve_points_won_pct",
        ),
        first_serve_in_pct=optional_float("scan_first_serve_in", "first_serve_in_pct"),
        current_set_first_serve_in_pct=optional_float(
            "scan_current_set_first_serve_in", "current_set_first_serve_in_pct"
        ),
        break_points_created=optional_int("scan_break_points_created", "break_points_created"),
        break_points_faced=optional_int("scan_break_points_faced", "break_points_faced"),
        comfortable_holds_pct=optional_float(
            "scan_comfortable_holds", "comfortable_holds_pct", allow_zero=True
        ),
        double_faults_per_service_game=(
            _as_optional_float(u.get("scan_df_rate"), allow_zero=True)
            if available("double_fault_rate")
            else None
        ),
        recent_form_label="Unknown",
        ranking=optional_int("scan_ranking", "ranking", allow_zero=False),
        opponent_ranking=optional_int(
            "scan_opponent_ranking", "opponent_ranking", allow_zero=False
        ),
        surface_form_label="Unknown",
        notes=" | ".join(mapping.warnings),
        data_completeness_pct=mapping.data_completeness_pct,
        core_completeness_pct=mapping.core_completeness_pct,
        event_key=str(u.get("scan_event_key") or "") or None,
        api_source=str(u.get("scan_api_source") or "live_api"),
        mapping_warnings=list(mapping.warnings),
        field_provenance={key: status.source for key, status in mapping.field_status.items()},
    )


def scan_both_players(
    event: Dict[str, Any],
    rankings: Optional[Mapping[Any, Any]] = None,
    *,
    price_by_player: Optional[Mapping[str, Any]] = None,
    bankroll: float = 0.0,
    market_price_timestamp: Optional[str] = None,
    market_volume: Optional[float] = None,
    market_liquidity: Optional[float] = None,
) -> List[PlayerScanResult]:
    """Always evaluate both player perspectives independently."""
    prices = price_by_player or {}
    players = [
        str(event.get("event_first_player") or "Unknown First Player"),
        str(event.get("event_second_player") or "Unknown Second Player"),
    ]
    results: List[PlayerScanResult] = []
    for player in players:
        try:
            mapping = build_live_scanner_mapping(event, player, rankings)
            match = match_from_mapping(
                mapping,
                market_price_cents=_lookup_price(prices, player),
                market_price_timestamp=market_price_timestamp,
                market_volume=market_volume,
                market_liquidity=market_liquidity,
                bankroll=bankroll,
            )
            results.append(PlayerScanResult(player, match, evaluate_match(match), mapping))
        except Exception as exc:
            # One malformed perspective must never prevent the other side from scanning.
            empty_mapping = LiveMappingResult(
                updates={"scan_player": player, "scan_opponent": "Unknown"},
                api_fields=[],
                calculated_fields=[],
                manual_fields=[],
                warnings=[],
                errors=[str(exc)],
                data_completeness_pct=0.0,
                core_completeness_pct=0.0,
            )
            match = MatchInput(
                player=player,
                opponent="Unknown",
                tournament=str(event.get("tournament_name") or "Unknown"),
            )
            results.append(
                PlayerScanResult(player, match, evaluate_match(match), empty_mapping, error=str(exc))
            )
    return results
