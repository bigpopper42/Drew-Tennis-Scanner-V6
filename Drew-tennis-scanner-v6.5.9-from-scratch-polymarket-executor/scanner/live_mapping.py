from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .event_pipeline import event_competition_group, event_league, is_singles_event

ALLOWED_GAME_SCORES = {
    "0-0", "15-0", "30-0", "40-0", "0-15", "15-15", "30-15", "40-15",
    "0-30", "15-30", "30-30", "40-30", "0-40", "15-40", "30-40",
    "Deuce", "Ad-In", "Ad-Out",
}
GRAND_SLAM_NAMES = {
    "australian open", "roland garros", "french open", "wimbledon", "us open", "u.s. open"
}

STAT_ALIASES: Dict[str, Sequence[str]] = {
    "service_points_won_pct": (
        "service points won", "service points won percentage", "service points won %"
    ),
    "first_serve_points_won_pct": (
        "1st serve points won", "first serve points won", "first-serve points won"
    ),
    "first_serve_in_pct": (
        "1st serve percentage", "first serve percentage", "first serves in"
    ),
    "double_faults": ("double faults", "double fault"),
    "break_points_saved": ("break points saved", "break point saved"),
    "break_points_created": ("break points converted", "break point converted"),
    "service_games_won": ("service games won",),
}


@dataclass
class FieldStatus:
    value: Any
    source: str
    available: bool
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "source": self.source,
            "available": self.available,
            "note": self.note,
        }


@dataclass
class LiveMappingResult:
    updates: Dict[str, Any]
    api_fields: List[str]
    calculated_fields: List[str]
    manual_fields: List[str]
    warnings: List[str]
    errors: List[str] = field(default_factory=list)
    field_status: Dict[str, FieldStatus] = field(default_factory=dict)
    data_completeness_pct: float = 0.0
    core_completeness_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "updates": self.updates,
            "api_fields": self.api_fields,
            "calculated_fields": self.calculated_fields,
            "manual_fields": self.manual_fields,
            "warnings": self.warnings,
            "errors": self.errors,
            "field_status": {key: value.to_dict() for key, value in self.field_status.items()},
            "data_completeness_pct": self.data_completeness_pct,
            "core_completeness_pct": self.core_completeness_pct,
        }


def normalized_event_type(event: Mapping[str, Any]) -> str:
    return str(event.get("event_type_type") or "").strip().lower()


def is_supported_singles(event: Mapping[str, Any]) -> bool:
    return is_singles_event(event)


def filter_supported_singles_events(
    events: Iterable[Dict[str, Any]],
    enabled_groups: Optional[Iterable[str]] = None,
) -> List[Dict[str, Any]]:
    allowed = set(enabled_groups or {"Tour", "Challenger"})
    return [
        event
        for event in events
        if is_singles_event(event)
        and event_league(event) == "ATP"
        and event_competition_group(event) in allowed
    ]


# Backward-compatible names used by previous versions.
def is_supported_atp_singles(event: Mapping[str, Any]) -> bool:
    return is_supported_singles(event)


def filter_supported_atp_events(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return filter_supported_singles_events(events)


def _side_for_player(event: Mapping[str, Any], backed_player: str) -> Tuple[str, Any, str, Any]:
    first = str(event.get("event_first_player") or "Unknown")
    second = str(event.get("event_second_player") or "Unknown")
    if backed_player == first:
        return "First Player", event.get("first_player_key"), second, event.get("second_player_key")
    if backed_player == second:
        return "Second Player", event.get("second_player_key"), first, event.get("first_player_key")
    # Last-resort case-insensitive comparison for provider formatting differences.
    if backed_player.strip().casefold() == first.strip().casefold():
        return "First Player", event.get("first_player_key"), second, event.get("second_player_key")
    if backed_player.strip().casefold() == second.strip().casefold():
        return "Second Player", event.get("second_player_key"), first, event.get("first_player_key")
    raise ValueError("The selected player does not match either player in the live event.")


def _other_side(side: str) -> str:
    return "Second Player" if side == "First Player" else "First Player"


def _safe_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    match = re.match(r"-?\d+", text)
    if not match:
        return None
    try:
        return int(match.group(0))
    except ValueError:
        return None


def _safe_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    text = str(value).strip().replace("%", "")
    try:
        number = float(text)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None


def _parse_set_number(event: Mapping[str, Any]) -> int:
    status = str(event.get("event_status") or "")
    match = re.search(r"(?:set|s)\s*(\d+)", status, flags=re.IGNORECASE)
    if match:
        return max(1, int(match.group(1)))

    set_numbers: List[int] = []
    for item in event.get("scores") or []:
        if not isinstance(item, Mapping):
            continue
        number = _safe_int(item.get("score_set"))
        if number:
            set_numbers.append(number)
    # When a match is live, the highest score set is normally the current set.
    return max(set_numbers, default=1)


def _integer_games(value: Any) -> int:
    number = _safe_int(value)
    return max(0, number or 0)


def _score_for_set(event: Mapping[str, Any], set_number: int) -> Tuple[int, int, bool]:
    for item in event.get("scores") or []:
        if not isinstance(item, Mapping):
            continue
        if _safe_int(item.get("score_set")) == set_number:
            return _integer_games(item.get("score_first")), _integer_games(item.get("score_second")), True
    return 0, 0, False


def _perspective_pair(first: Any, second: Any, side: str) -> Tuple[Any, Any]:
    return (first, second) if side == "First Player" else (second, first)


def _normalize_point_token(value: str) -> str:
    token = value.strip().upper()
    if token in {"A", "AD", "ADV", "ADVANTAGE"}:
        return "A"
    if token in {"LOVE", "00"}:
        return "0"
    return token


def normalize_game_score(raw_score: Any, side: str, tiebreak: bool) -> str:
    if tiebreak:
        return "0-0"
    text = str(raw_score or "0 - 0").strip().replace("–", "-")
    parts = [part.strip() for part in text.split("-")]
    if len(parts) != 2:
        return "0-0"
    first, second = _normalize_point_token(parts[0]), _normalize_point_token(parts[1])
    backed, opponent = _perspective_pair(first, second, side)
    if backed == "40" and opponent == "40":
        return "Deuce"
    if backed == "A":
        return "Ad-In"
    if opponent == "A":
        return "Ad-Out"
    normalized = f"{backed}-{opponent}"
    return normalized if normalized in ALLOWED_GAME_SCORES else "0-0"


def _set_number_from_entry(item: Mapping[str, Any]) -> Optional[int]:
    match = re.search(r"set\s*(\d+)", str(item.get("set_number") or ""), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _point_entries(event: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    return [row for row in (event.get("pointbypoint") or []) if isinstance(row, Mapping)]


def _current_set_entries(event: Mapping[str, Any], set_number: int) -> List[Mapping[str, Any]]:
    return [row for row in _point_entries(event) if _set_number_from_entry(row) == set_number]


def _is_tiebreak(event: Mapping[str, Any], set_number: int) -> bool:
    entries = _current_set_entries(event, set_number)
    if entries and any("tiebreak" in str(entry.get("set_number") or "").lower() for entry in entries[-2:]):
        return True
    first_games, second_games, found = _score_for_set(event, set_number)
    raw_game = str(event.get("event_game_result") or "")
    if found and first_games == 6 and second_games == 6:
        return bool(re.fullmatch(r"\s*\d+\s*-\s*\d+\s*", raw_game))
    status = str(event.get("event_status") or "").lower()
    return "tiebreak" in status or "tie break" in status


def _game_number_from_entry(item: Mapping[str, Any]) -> Optional[int]:
    value = _safe_int(item.get("number_game"))
    return value if value is not None and value > 0 else None


def _completed_games(event: Mapping[str, Any]) -> List[Mapping[str, Any]]:
    """Return one completed row per set/game from API Tennis point-by-point data.

    API Tennis can repeat a completed game in later snapshots. Counting those
    rows twice fabricates breaks and can produce impossible states such as a
    two-break lead at 1-0. Numbered rows are therefore keyed by
    ``(set_number, number_game)`` and the latest complete snapshot wins.
    """

    numbered: Dict[Tuple[int, int], Mapping[str, Any]] = {}
    unnumbered: List[Mapping[str, Any]] = []
    for item in _point_entries(event):
        if "tiebreak" in str(item.get("set_number") or "").lower():
            continue
        if item.get("serve_winner") not in {"First Player", "Second Player"}:
            continue
        set_number = _set_number_from_entry(item)
        game_number = _game_number_from_entry(item)
        if set_number is not None and game_number is not None:
            numbered[(set_number, game_number)] = item
        else:
            unnumbered.append(item)
    ordered = [numbered[key] for key in sorted(numbered)]
    return ordered + unnumbered


def _completed_games_for_set(
    event: Mapping[str, Any], set_number: int
) -> List[Mapping[str, Any]]:
    rows = [game for game in _completed_games(event) if _set_number_from_entry(game) == set_number]
    first_games, second_games, score_found = _score_for_set(event, set_number)
    if not score_found:
        return rows

    completed_count = max(0, first_games + second_games)
    numbered = [game for game in rows if _game_number_from_entry(game) is not None]
    if numbered:
        # Ignore future/stale rows that contradict the authoritative current set
        # score. This also prevents duplicate feed snapshots from inflating the
        # calculated break lead.
        return [
            game
            for game in numbered
            if (_game_number_from_entry(game) or 0) <= completed_count
        ]
    return rows[:completed_count]


def _breaks_suffered_by_set(event: Mapping[str, Any], side: str, completed_sets: int) -> List[int]:
    counts = {number: 0 for number in range(1, max(0, completed_sets) + 1)}
    opponent = _other_side(side)
    for game in _completed_games(event):
        number = _set_number_from_entry(game)
        if number in counts and game.get("player_served") == side and game.get("serve_winner") == opponent:
            counts[number] += 1
    return [counts[number] for number in sorted(counts)]


def _total_breaks_suffered(event: Mapping[str, Any], side: str) -> Optional[int]:
    games = _completed_games(event)
    if not games:
        return None
    opponent = _other_side(side)
    return sum(1 for game in games if game.get("player_served") == side and game.get("serve_winner") == opponent)


def _current_break_lead_from_points(event: Mapping[str, Any], side: str, set_number: int, tiebreak: bool) -> Optional[int]:
    if tiebreak:
        return 0
    games = _completed_games_for_set(event, set_number)
    if not games:
        return None
    opponent = _other_side(side)
    made = sum(1 for game in games if game.get("player_served") == opponent and game.get("serve_winner") == side)
    lost = sum(1 for game in games if game.get("player_served") == side and game.get("serve_winner") == opponent)
    return max(0, made - lost)




def _current_set_breaks_suffered(
    event: Mapping[str, Any], side: str, set_number: int
) -> Optional[int]:
    games = _completed_games_for_set(event, set_number)
    if not games:
        return None
    opponent = _other_side(side)
    return sum(
        1
        for game in games
        if game.get("player_served") == side and game.get("serve_winner") == opponent
    )


def _break_points_created(
    event: Mapping[str, Any], side: str, player_key: Any
) -> Tuple[Optional[int], str]:
    converted = _find_stat(event, player_key, "break_points_created")
    if converted:
        total = _safe_int(converted.get("stat_total"))
        if total is not None:
            return max(0, total), "API Tennis break-point opportunities"

    opponent = _other_side(side)
    return_games = [
        game for game in _completed_games(event)
        if game.get("player_served") == opponent
    ]
    if not return_games:
        return None, "Unavailable"
    count = 0
    for game in return_games:
        for point in game.get("points") or []:
            if isinstance(point, Mapping) and point.get("break_point") not in (None, "", False, "0", 0):
                count += 1
    return count, "Calculated from point-by-point"

def _current_break_lead_fallback(
    event: Mapping[str, Any],
    side: str,
    set_number: int,
    tiebreak: bool,
) -> Tuple[int, str]:
    """Conservative score-based fallback when point-by-point is absent.

    It only awards a break lead when the backed player is ahead by at least two
    games. This can undercount some one-break states, but it avoids inventing a
    trade setup from ambiguous score parity.
    """
    if tiebreak:
        return 0, "tiebreak"
    first, second, found = _score_for_set(event, set_number)
    if not found:
        return 0, "missing"
    backed, opponent = _perspective_pair(first, second, side)
    difference = backed - opponent
    if difference >= 4:
        return 2, "score fallback"
    if difference >= 2:
        return 1, "score fallback"
    return 0, "score fallback"


def _normalize_stat_name(value: Any) -> str:
    text = str(value or "").strip().lower().replace("%", " percentage ")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return " ".join(text.split())


def _stat_records(
    event: Mapping[str, Any],
    player_key: Any,
    period: Optional[str] = "match",
) -> List[Mapping[str, Any]]:
    key = str(player_key)
    wanted = _normalize_stat_name(period) if period else ""
    rows: List[Mapping[str, Any]] = []
    for stat in event.get("statistics") or []:
        if not isinstance(stat, Mapping):
            continue
        if str(stat.get("player_key")) != key:
            continue
        stat_period = _normalize_stat_name(stat.get("stat_period"))
        if wanted in {"match", "full match"}:
            if stat_period and stat_period not in {"match", "full match"}:
                continue
        elif wanted and stat_period != wanted:
            continue
        rows.append(stat)
    return rows


def _find_stat(
    event: Mapping[str, Any],
    player_key: Any,
    alias_key: str,
    period: Optional[str] = "match",
) -> Optional[Mapping[str, Any]]:
    aliases = {_normalize_stat_name(alias) for alias in STAT_ALIASES[alias_key]}
    records = _stat_records(event, player_key, period)
    for stat in records:
        if _normalize_stat_name(stat.get("stat_name")) in aliases:
            return stat
    # Fuzzy containment fallback for harmless punctuation/wording changes.
    for stat in records:
        name = _normalize_stat_name(stat.get("stat_name"))
        if any(alias in name or name in alias for alias in aliases if name):
            return stat
    return None


def _percent_from_stat(stat: Optional[Mapping[str, Any]]) -> Optional[float]:
    if not stat:
        return None
    direct = _safe_float(stat.get("stat_value"))
    if direct is not None:
        return max(0.0, min(100.0, direct))
    won, total = _safe_float(stat.get("stat_won")), _safe_float(stat.get("stat_total"))
    if won is not None and total and total > 0:
        return round(won / total * 100, 1)
    return None


def _number_from_stat(stat: Optional[Mapping[str, Any]]) -> Optional[float]:
    if not stat:
        return None
    value = _safe_float(stat.get("stat_value"))
    if value is not None:
        return value
    return _safe_float(stat.get("stat_total"))


def _service_points_won(
    event: Mapping[str, Any],
    player_key: Any,
    period: Optional[str] = "match",
) -> Tuple[Optional[float], str]:
    direct = _percent_from_stat(_find_stat(event, player_key, "service_points_won_pct", period))
    if direct is not None:
        return direct, "API Tennis statistics"

    first = _find_stat(event, player_key, "first_serve_points_won_pct", period)
    second_aliases = {_normalize_stat_name(name) for name in ("2nd serve points won", "second serve points won")}
    second = next(
        (
            stat for stat in _stat_records(event, player_key, period)
            if _normalize_stat_name(stat.get("stat_name")) in second_aliases
        ),
        None,
    )
    first_won, first_total = (_safe_float(first.get("stat_won")), _safe_float(first.get("stat_total"))) if first else (None, None)
    second_won, second_total = (_safe_float(second.get("stat_won")), _safe_float(second.get("stat_total"))) if second else (None, None)
    if None not in (first_won, first_total, second_won, second_total) and (first_total + second_total) > 0:
        return round((first_won + second_won) / (first_total + second_total) * 100, 1), "Calculated from serve-point totals"
    return None, "Unavailable"


def _break_points_faced(event: Mapping[str, Any], side: str, player_key: Any) -> Tuple[Optional[int], str]:
    saved = _find_stat(event, player_key, "break_points_saved")
    if saved:
        total = _safe_int(saved.get("stat_total"))
        if total is not None:
            return max(0, total), "API Tennis stat_total"
        # Some feeds encode “saved/total” only through won and total.
        value = _safe_int(saved.get("stat_value"))
        if value is not None:
            return max(0, value), "API Tennis stat_value"

    service_games = [game for game in _completed_games(event) if game.get("player_served") == side]
    if not service_games:
        return None, "Unavailable"
    count = 0
    for game in service_games:
        for point in game.get("points") or []:
            if isinstance(point, Mapping) and point.get("break_point") not in (None, "", False, "0", 0):
                count += 1
    return count, "Calculated from point-by-point"


def _service_games_played(event: Mapping[str, Any], side: str) -> int:
    return sum(1 for game in _completed_games(event) if game.get("player_served") == side)


def _comfortable_holds_pct(event: Mapping[str, Any], side: str) -> Tuple[Optional[float], str]:
    service_games = [game for game in _completed_games(event) if game.get("player_served") == side]
    if not service_games:
        return None, "Unavailable"
    comfortable = 0
    for game in service_games:
        held = game.get("serve_winner") == side
        faced_break = any(
            isinstance(point, Mapping) and point.get("break_point") not in (None, "", False, "0", 0)
            for point in (game.get("points") or [])
        )
        if held and not faced_break:
            comfortable += 1
    return round(comfortable / len(service_games) * 100, 1), "Calculated from service games"


def _double_fault_rate(event: Mapping[str, Any], side: str, player_key: Any) -> Tuple[Optional[float], str]:
    faults = _number_from_stat(_find_stat(event, player_key, "double_faults"))
    service_games = _service_games_played(event, side)
    if faults is None or service_games <= 0:
        return None, "Unavailable"
    return round(max(0.0, faults) / service_games, 2), "Calculated from API double faults / service games"


def _best_of_sets(event: Mapping[str, Any]) -> int:
    tournament = str(event.get("tournament_name") or "").lower()
    if event_league(event) == "ATP" and any(name in tournament for name in GRAND_SLAM_NAMES):
        return 5
    return 3


def _set_wins(event: Mapping[str, Any]) -> Tuple[int, int]:
    result = str(event.get("event_final_result") or "0 - 0").replace("–", "-")
    parts = [part.strip() for part in result.split("-")]
    if len(parts) == 2:
        first, second = _safe_int(parts[0]), _safe_int(parts[1])
        if first is not None and second is not None:
            return max(0, first), max(0, second)

    first_sets = second_sets = 0
    current_set = _parse_set_number(event)
    for item in event.get("scores") or []:
        if not isinstance(item, Mapping):
            continue
        set_number = _safe_int(item.get("score_set"))
        if not set_number or set_number >= current_set:
            continue
        first, second = _integer_games(item.get("score_first")), _integer_games(item.get("score_second"))
        if first > second:
            first_sets += 1
        elif second > first:
            second_sets += 1
    return first_sets, second_sets


def _match_closing_set(event: Mapping[str, Any], side: str) -> bool:
    first_sets, second_sets = _set_wins(event)
    backed_sets, _ = _perspective_pair(first_sets, second_sets, side)
    needed = _best_of_sets(event) // 2 + 1
    return backed_sets == needed - 1


def _ranking_for_player(rankings: Optional[Mapping[Any, Any]], player_key: Any, league: str) -> Optional[int]:
    if not rankings or player_key is None:
        return None
    selected: Mapping[Any, Any] = rankings
    if isinstance(rankings, Mapping) and isinstance(rankings.get(league), Mapping):
        selected = rankings[league]
    for candidate in (player_key, str(player_key)):
        if candidate in selected:
            try:
                return int(float(selected[candidate]))
            except (TypeError, ValueError):
                return None
    return None


def _field(
    statuses: Dict[str, FieldStatus],
    name: str,
    value: Any,
    source: str,
    *,
    available: Optional[bool] = None,
    note: str = "",
) -> Any:
    present = value not in (None, "", [], {}) if available is None else available
    statuses[name] = FieldStatus(value=value, source=source, available=bool(present), note=note)
    return value


def _completeness(statuses: Mapping[str, FieldStatus], names: Sequence[str]) -> float:
    if not names:
        return 0.0
    available = sum(1 for name in names if statuses.get(name) and statuses[name].available)
    return round(available / len(names) * 100, 1)


def build_live_scanner_mapping(
    event: Dict[str, Any],
    backed_player: str,
    rankings: Optional[Mapping[Any, Any]] = None,
) -> LiveMappingResult:
    """Map one API Tennis event into one backed-player perspective.

    Missing values remain explicit in ``field_status``. Version 6.0 never
    invents a qualifying statistic: missing critical service data can pass only
    through the narrow two-break/ranking fallback in the hard rules.
    """
    side, player_key, opponent, opponent_key = _side_for_player(event, backed_player)
    league = event_league(event)
    group = event_competition_group(event)
    set_number = _parse_set_number(event)
    period = f"set{set_number}"
    tiebreak = _is_tiebreak(event, set_number)
    first_games, second_games, score_found = _score_for_set(event, set_number)
    backed_games, opponent_games = _perspective_pair(first_games, second_games, side)
    completed_sets = max(0, set_number - 1)

    statuses: Dict[str, FieldStatus] = {}
    warnings: List[str] = []
    errors: List[str] = []

    break_lead = _current_break_lead_from_points(event, side, set_number, tiebreak)
    break_source = "Calculated from point-by-point"
    if break_lead is None:
        break_lead, break_source = _current_break_lead_fallback(event, side, set_number, tiebreak)
        warnings.append(
            "Current break lead used the conservative score fallback because point-by-point data was unavailable."
        )

    full_service, full_service_source = _service_points_won(event, player_key, "match")
    current_service, current_service_source = _service_points_won(event, player_key, period)
    opponent_full_service, opponent_full_source = _service_points_won(event, opponent_key, "match")
    opponent_current_service, opponent_current_source = _service_points_won(event, opponent_key, period)

    first_serve_points = _percent_from_stat(
        _find_stat(event, player_key, "first_serve_points_won_pct", "match")
    )
    current_first_serve_points = _percent_from_stat(
        _find_stat(event, player_key, "first_serve_points_won_pct", period)
    )
    first_serve_in = _percent_from_stat(
        _find_stat(event, player_key, "first_serve_in_pct", "match")
    )
    current_first_serve_in = _percent_from_stat(
        _find_stat(event, player_key, "first_serve_in_pct", period)
    )

    break_points_faced, break_points_source = _break_points_faced(event, side, player_key)
    break_points_created, break_created_source = _break_points_created(event, side, player_key)
    comfortable_holds, comfortable_source = _comfortable_holds_pct(event, side)
    df_rate, df_source = _double_fault_rate(event, side, player_key)
    total_breaks = _total_breaks_suffered(event, side)
    current_set_breaks = _current_set_breaks_suffered(event, side, set_number)
    breaks_by_set = _breaks_suffered_by_set(event, side, completed_sets)

    ranking = _ranking_for_player(rankings, player_key, league)
    opponent_ranking = _ranking_for_player(rankings, opponent_key, league)

    serving_value: Optional[bool] = None
    if event.get("event_serve") in {"First Player", "Second Player"}:
        serving_value = event.get("event_serve") == side

    first_sets, second_sets = _set_wins(event)
    backed_sets, opponent_sets = _perspective_pair(first_sets, second_sets, side)
    best_of = _best_of_sets(event)
    sets_needed = best_of // 2 + 1
    match_closing = backed_sets == sets_needed - 1
    straight_set_closing = match_closing and opponent_sets == 0
    deciding_set = match_closing and opponent_sets == sets_needed - 1
    serving_for_match = bool(
        serving_value is True
        and match_closing
        and not tiebreak
        and backed_games >= 5
        and backed_games > opponent_games
    )

    # The effective service figure is included for display/recording. Scoring
    # recomputes the same locked weighting from raw current/full values.
    effective_service: Optional[float]
    if current_service is not None and full_service is not None:
        current_weight = 0.65 if deciding_set else 0.30
        effective_service = round(
            current_weight * current_service + (1.0 - current_weight) * full_service,
            1,
        )
    else:
        effective_service = current_service if current_service is not None else full_service

    updates: Dict[str, Any] = {
        "scan_player": backed_player,
        "scan_opponent": opponent,
        "scan_tournament": str(event.get("tournament_name") or "Unknown tournament"),
        "scan_event_type": str(event.get("event_type_type") or "Unknown"),
        "scan_league": league,
        "scan_competition_group": group,
        "scan_surface": "Unknown",
        "scan_ranking": ranking or 0,
        "scan_opponent_ranking": opponent_ranking or 0,
        "scan_best_of_sets": best_of,
        "scan_match_closing_set": match_closing,
        "scan_straight_set_closing": straight_set_closing,
        "scan_deciding_set": deciding_set,
        "scan_break_lead": break_lead,
        "scan_serving": bool(serving_value),
        "scan_serving_for_match": serving_for_match,
        "scan_tiebreak": tiebreak,
        "scan_games_in_set": backed_games,
        "scan_opponent_games_in_set": opponent_games,
        "scan_game_score": normalize_game_score(event.get("event_game_result"), side, tiebreak),
        "scan_completed_sets": completed_sets,
        "scan_breaks_by_set": ",".join(str(value) for value in breaks_by_set),
        "scan_breaks_total": total_breaks if total_breaks is not None else 0,
        "scan_current_set_breaks": current_set_breaks if current_set_breaks is not None else 0,
        "scan_service_points": full_service if full_service is not None else 0.0,
        "scan_current_set_service_points": current_service if current_service is not None else 0.0,
        "scan_effective_service_points": effective_service if effective_service is not None else 0.0,
        "scan_opponent_service_points": opponent_full_service if opponent_full_service is not None else 0.0,
        "scan_opponent_current_set_service_points": (
            opponent_current_service if opponent_current_service is not None else 0.0
        ),
        "scan_first_serve_points": first_serve_points if first_serve_points is not None else 0.0,
        "scan_current_set_first_serve_points": (
            current_first_serve_points if current_first_serve_points is not None else 0.0
        ),
        "scan_first_serve_in": first_serve_in if first_serve_in is not None else 0.0,
        "scan_current_set_first_serve_in": (
            current_first_serve_in if current_first_serve_in is not None else 0.0
        ),
        "scan_break_points_created": break_points_created if break_points_created is not None else 0,
        "scan_break_points_faced": break_points_faced if break_points_faced is not None else 0,
        "scan_comfortable_holds": comfortable_holds if comfortable_holds is not None else 0.0,
        "scan_df_rate": df_rate if df_rate is not None else 0.0,
        "scan_recent_form": "Unknown",
        "scan_surface_form": "Unknown",
        "scan_source": "live_api",
        "scan_event_key": str(event.get("event_key") or ""),
        "scan_api_source": str(event.get("_api_source") or "get_livescore"),
    }

    _field(statuses, "player", backed_player, "API Tennis")
    _field(statuses, "opponent", opponent, "API Tennis")
    _field(statuses, "tournament", updates["scan_tournament"], "API Tennis")
    _field(statuses, "event_type", updates["scan_event_type"], "API Tennis")
    _field(statuses, "league", league, "Calculated from API Tennis event")
    _field(statuses, "competition_group", group, "Calculated from API Tennis event")
    _field(statuses, "best_of_sets", best_of, "Calculated from tournament format")
    _field(statuses, "current_set", set_number, "event_status / scores")
    _field(statuses, "set_score", f"{first_games}-{second_games}", "scores", available=score_found)
    _field(
        statuses,
        "current_game_score",
        updates["scan_game_score"],
        "event_game_result",
        available=bool(event.get("event_game_result")),
    )
    _field(statuses, "serving", serving_value, "event_serve", available=serving_value is not None)
    _field(statuses, "serving_for_match", serving_for_match, "Calculated from match/set/game state")
    _field(statuses, "match_closing_set", match_closing, "Calculated from set score")
    _field(statuses, "straight_set_closing", straight_set_closing, "Calculated from set score")
    _field(statuses, "deciding_set", deciding_set, "Calculated from set score")
    _field(statuses, "break_lead", break_lead, break_source, available=break_source != "missing")
    _field(statuses, "tiebreak", tiebreak, "scores / point-by-point / status")
    _field(statuses, "games_in_set", backed_games, "scores", available=score_found)
    _field(statuses, "opponent_games_in_set", opponent_games, "scores", available=score_found)
    _field(
        statuses,
        "service_points_won_pct",
        full_service,
        full_service_source,
        available=full_service is not None,
    )
    _field(
        statuses,
        "current_set_service_points_won_pct",
        current_service,
        current_service_source,
        available=current_service is not None,
    )
    _field(
        statuses,
        "effective_service_points_won_pct",
        effective_service,
        "Calculated using Version 6.0 set weighting",
        available=effective_service is not None,
    )
    _field(
        statuses,
        "opponent_service_points_won_pct",
        opponent_full_service,
        opponent_full_source,
        available=opponent_full_service is not None,
    )
    _field(
        statuses,
        "opponent_current_set_service_points_won_pct",
        opponent_current_service,
        opponent_current_source,
        available=opponent_current_service is not None,
    )
    _field(
        statuses,
        "first_serve_points_won_pct",
        first_serve_points,
        "API Tennis match statistics",
        available=first_serve_points is not None,
    )
    _field(
        statuses,
        "current_set_first_serve_points_won_pct",
        current_first_serve_points,
        f"API Tennis {period} statistics",
        available=current_first_serve_points is not None,
    )
    _field(
        statuses,
        "first_serve_in_pct",
        first_serve_in,
        "API Tennis match statistics",
        available=first_serve_in is not None,
    )
    _field(
        statuses,
        "current_set_first_serve_in_pct",
        current_first_serve_in,
        f"API Tennis {period} statistics",
        available=current_first_serve_in is not None,
    )
    _field(
        statuses,
        "breaks_suffered_total",
        total_breaks,
        "Calculated from point-by-point",
        available=total_breaks is not None,
    )
    _field(
        statuses,
        "current_set_breaks_suffered",
        current_set_breaks,
        "Calculated from current-set point-by-point",
        available=current_set_breaks is not None,
    )
    _field(
        statuses,
        "break_points_created",
        break_points_created,
        break_created_source,
        available=break_points_created is not None,
    )
    _field(
        statuses,
        "break_points_faced",
        break_points_faced,
        break_points_source,
        available=break_points_faced is not None,
    )
    _field(
        statuses,
        "comfortable_holds_pct",
        comfortable_holds,
        comfortable_source,
        available=comfortable_holds is not None,
        note="Recorded for diagnostics only; deliberately not scored in Version 6.0.",
    )
    _field(statuses, "double_fault_rate", df_rate, df_source, available=df_rate is not None)
    _field(statuses, "ranking", ranking, f"{league} standings", available=ranking is not None)
    _field(
        statuses,
        "opponent_ranking",
        opponent_ranking,
        f"{league} standings",
        available=opponent_ranking is not None,
    )
    _field(statuses, "surface", None, "Not supplied reliably by API Tennis", available=False)
    _field(statuses, "recent_form", None, "Removed from Version 6.0 score", available=False)
    _field(statuses, "bankroll", None, "Manual optional field", available=False)
    _field(
        statuses,
        "market_price",
        None,
        "Polymarket informational field; never used in qualification or sizing",
        available=False,
    )

    critical_labels = {
        "service_points_won_pct": "Full-match service points won %",
        "current_set_service_points_won_pct": "Current-set service points won %",
        "current_set_breaks_suffered": "Current-set breaks suffered",
        "break_points_created": "Break points created",
        "break_points_faced": "Break points faced",
        "opponent_service_points_won_pct": "Opponent service points won %",
        "ranking": f"Official {league} ranking" if league in {"ATP", "WTA"} else "Official ranking",
        "opponent_ranking": f"Opponent {league} ranking" if league in {"ATP", "WTA"} else "Opponent ranking",
    }
    for field_name, label in critical_labels.items():
        if not statuses[field_name].available:
            warnings.append(
                f"{label} is unavailable; Version 6.0 will not invent the value and qualification may be blocked."
            )

    if serving_value is None:
        warnings.append("Current server is unavailable, so serving-dependent one-break rules cannot qualify.")
    if not score_found:
        warnings.append("Current-set score is unavailable, so score-dependent confirmation cannot qualify.")

    core_names = [
        "player",
        "opponent",
        "league",
        "competition_group",
        "current_set",
        "set_score",
        "current_game_score",
        "serving",
        "match_closing_set",
        "break_lead",
        "tiebreak",
        "games_in_set",
        "opponent_games_in_set",
        "current_set_breaks_suffered",
    ]
    scored_names = [
        "service_points_won_pct",
        "current_set_service_points_won_pct",
        "first_serve_points_won_pct",
        "current_set_first_serve_points_won_pct",
        "first_serve_in_pct",
        "current_set_first_serve_in_pct",
        "break_points_created",
        "break_points_faced",
        "opponent_service_points_won_pct",
        "opponent_current_set_service_points_won_pct",
        "double_fault_rate",
        "ranking",
        "opponent_ranking",
        "break_lead",
        "serving",
        "games_in_set",
    ]
    core_pct = _completeness(statuses, core_names)
    data_pct = _completeness(statuses, scored_names)
    updates["scan_data_completeness"] = data_pct
    updates["scan_core_completeness"] = core_pct

    api_fields = [
        name
        for name, status in statuses.items()
        if status.available and status.source.startswith("API Tennis")
    ]
    calculated_fields = [
        name
        for name, status in statuses.items()
        if status.available and "Calculated" in status.source
    ]
    manual_fields = ["Surface (ignored)", "Bankroll (optional)", "Polymarket data (informational only)"]

    return LiveMappingResult(
        updates=updates,
        api_fields=list(dict.fromkeys(api_fields)),
        calculated_fields=list(dict.fromkeys(calculated_fields)),
        manual_fields=manual_fields,
        warnings=list(dict.fromkeys(warnings)),
        errors=errors,
        field_status=statuses,
        data_completeness_pct=data_pct,
        core_completeness_pct=core_pct,
    )
