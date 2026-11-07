"""Match Polymarket tennis events to API Tennis live events.

The matching logic is deliberately conservative. A wrong event match is more
dangerous than an unmatched event, so ambiguous candidates remain visible for
manual review instead of being silently attached.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from scanner.live_mapping import is_supported_singles

ALIASES_PATH = Path("data/player_aliases.json")
FULL_STATS = "FULL_STATS"
PARTIAL_STATS = "PARTIAL_STATS"
SCORE_ONLY = "SCORE_ONLY"
UNMATCHED = "UNMATCHED"
AMBIGUOUS = "AMBIGUOUS"

REQUIRED_SERVICE_STATS = {
    "service points won",
    "1st serve points won",
    "1st serve percentage",
}


@dataclass
class ReconciliationRow:
    polymarket_event_id: Any
    polymarket_event_title: str
    polymarket_market_id: Any
    polymarket_market_title: str
    player1: str
    player2: str
    api_event_key: Any
    api_player1: str
    api_player2: str
    api_tournament: str
    confidence: float
    match_status: str
    data_tier: str
    data_confidence: float
    reversed_order: bool
    reason: str
    match_winner_market: bool
    polymarket_score: Any = None
    api_score: Any = None
    market_slug: Optional[str] = None
    market_confidence: float = 0.0
    source_index: Optional[int] = None
    api_index: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    value = value.lower().replace("’", "'")
    value = re.sub(r"\([^)]*\)", " ", value)
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    return " ".join(value.split())


def normalize_player_name(value: str) -> str:
    text = normalize_text(value)
    # Remove common country/ranking suffixes without deleting legitimate initials.
    tokens = [token for token in text.split() if token not in {"atp", "wta", "seed", "rank"}]
    return " ".join(tokens)


def _token_initial(token: str) -> str:
    return token[0] if token else ""


def _name_parts(value: str) -> Tuple[List[str], str, str]:
    normalized = normalize_player_name(value)
    tokens = normalized.split()
    surname = tokens[-1] if tokens else ""
    first = tokens[0] if tokens else ""
    return tokens, surname, first


def name_similarity(left: str, right: str, aliases: Optional[Mapping[str, str]] = None) -> float:
    """Return a conservative 0-1 player-name similarity score."""
    left_norm = normalize_player_name(left)
    right_norm = normalize_player_name(right)
    alias_map = aliases or {}
    left_norm = normalize_player_name(alias_map.get(left_norm, left_norm))
    right_norm = normalize_player_name(alias_map.get(right_norm, right_norm))

    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0

    left_tokens, left_surname, left_first = _name_parts(left_norm)
    right_tokens, right_surname, right_first = _name_parts(right_norm)

    if left_surname and left_surname == right_surname:
        if left_first == right_first:
            return 0.98
        if _token_initial(left_first) == _token_initial(right_first):
            # Covers "A. Zverev" vs "Alexander Zverev".
            return 0.94
        first_ratio = SequenceMatcher(None, left_first, right_first).ratio()
        if first_ratio >= 0.8:
            return 0.90
        # Same surname without a compatible first name is risky (e.g. Williams).
        return 0.68

    left_joined = " ".join(left_tokens)
    right_joined = " ".join(right_tokens)
    sequence = SequenceMatcher(None, left_joined, right_joined).ratio()
    token_overlap = len(set(left_tokens) & set(right_tokens)) / max(len(set(left_tokens) | set(right_tokens)), 1)
    return min(0.89, sequence * 0.75 + token_overlap * 0.25)


def load_aliases(path: Path = ALIASES_PATH) -> Dict[str, str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        normalize_player_name(str(alias)): normalize_player_name(str(canonical))
        for alias, canonical in payload.items()
        if alias and canonical
    }


def save_alias(alias: str, canonical: str, path: Path = ALIASES_PATH) -> None:
    aliases = load_aliases(path)
    alias_norm = normalize_player_name(alias)
    canonical_norm = normalize_player_name(canonical)
    if not alias_norm or not canonical_norm:
        raise ValueError("Alias and canonical player name are required.")
    aliases[alias_norm] = canonical_norm
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(aliases, indent=2, sort_keys=True), encoding="utf-8")


def _parse_datetime(value: Any) -> Optional[datetime]:
    text = str(value or "").strip()
    if not text:
        return None
    text = text.replace("Z", "+00:00")
    formats = (
        None,
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    )
    for fmt in formats:
        try:
            parsed = datetime.fromisoformat(text) if fmt is None else datetime.strptime(text, fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _api_event_datetime(event: Mapping[str, Any]) -> Optional[datetime]:
    combined = " ".join(
        part
        for part in (str(event.get("event_date") or "").strip(), str(event.get("event_time") or "").strip())
        if part
    )
    return _parse_datetime(combined or event.get("event_start") or event.get("event_date"))


def _time_score(pm_start: Any, api_event: Mapping[str, Any]) -> Tuple[float, str]:
    left = _parse_datetime(pm_start)
    right = _api_event_datetime(api_event)
    if not left or not right:
        return 0.5, "start time unavailable"
    difference_minutes = abs((left - right).total_seconds()) / 60
    if difference_minutes <= 30:
        return 1.0, f"start times within {difference_minutes:.0f} minutes"
    if difference_minutes <= 120:
        return 0.8, f"start times within {difference_minutes:.0f} minutes"
    if difference_minutes <= 360:
        return 0.45, f"start times differ by {difference_minutes:.0f} minutes"
    return 0.0, f"start times differ by {difference_minutes:.0f} minutes"


def _tournament_score(pm_row: Mapping[str, Any], api_event: Mapping[str, Any]) -> Tuple[float, str]:
    raw_event = pm_row.get("raw_event") or {}
    tournament_parts = [
        str(pm_row.get("series_slug") or ""),
        str(raw_event.get("subtitle") or ""),
        str(raw_event.get("seriesSlug") or ""),
        str((raw_event.get("series") or {}).get("title") or "") if isinstance(raw_event.get("series") or {}, dict) else "",
    ]
    pm_text = normalize_text(" ".join(part for part in tournament_parts if part))
    if not pm_text:
        # Fall back to the event title after removing both player names.
        title = str(pm_row.get("event_title") or "")
        for player_key in ("player1", "player2"):
            player = str(pm_row.get(player_key) or "")
            if player:
                title = re.sub(re.escape(player), " ", title, flags=re.IGNORECASE)
        pm_text = normalize_text(title)
    api_text = normalize_text(
        " ".join(
            [
                str(api_event.get("tournament_name") or ""),
                str(api_event.get("event_type_type") or ""),
                str(api_event.get("event_type_key") or ""),
            ]
        )
    )
    if not pm_text or not api_text:
        return 0.5, "tournament metadata unavailable"
    ratio = SequenceMatcher(None, pm_text, api_text).ratio()
    overlap = len(set(pm_text.split()) & set(api_text.split())) / max(len(set(api_text.split())), 1)
    score = min(1.0, ratio * 0.55 + overlap * 0.45)
    if score >= 0.7:
        return score, "tournament metadata agrees"
    if score >= 0.4:
        return score, "tournament metadata is only partially similar"
    return score, "tournament metadata conflicts"


def _api_players(event: Mapping[str, Any]) -> Tuple[str, str]:
    return str(event.get("event_first_player") or ""), str(event.get("event_second_player") or "")


def _pair_score(
    pm_players: Sequence[str],
    api_players: Sequence[str],
    aliases: Mapping[str, str],
) -> Tuple[float, bool, Tuple[float, float]]:
    if len(pm_players) < 2 or len(api_players) < 2:
        return 0.0, False, (0.0, 0.0)
    direct = (
        name_similarity(pm_players[0], api_players[0], aliases),
        name_similarity(pm_players[1], api_players[1], aliases),
    )
    reversed_pair = (
        name_similarity(pm_players[0], api_players[1], aliases),
        name_similarity(pm_players[1], api_players[0], aliases),
    )
    direct_score = min(direct) * 0.7 + sum(direct) / 2 * 0.3
    reversed_score = min(reversed_pair) * 0.7 + sum(reversed_pair) / 2 * 0.3
    if reversed_score > direct_score:
        return reversed_score, True, reversed_pair
    return direct_score, False, direct


def _stat_names_for_player(event: Mapping[str, Any], player_key: Any) -> set[str]:
    key = str(player_key)
    names: set[str] = set()
    for row in event.get("statistics") or []:
        if str(row.get("player_key")) != key:
            continue
        if str(row.get("stat_period") or "").strip().lower() != "match":
            continue
        name = normalize_text(str(row.get("stat_name") or ""))
        if name:
            names.add(name)
    return names


def classify_data_quality(event: Optional[Mapping[str, Any]]) -> Tuple[str, float, str]:
    if not event:
        return UNMATCHED, 0.0, "No API Tennis event was matched."

    score_present = bool(event.get("scores") or str(event.get("event_final_result") or "").strip())
    current_game = bool(str(event.get("event_game_result") or "").strip())
    server = str(event.get("event_serve") or "") in {"First Player", "Second Player"}
    point_by_point = bool(event.get("pointbypoint"))
    statistics = bool(event.get("statistics"))

    first_names = _stat_names_for_player(event, event.get("first_player_key"))
    second_names = _stat_names_for_player(event, event.get("second_player_key"))
    first_complete = REQUIRED_SERVICE_STATS.issubset(first_names)
    second_complete = REQUIRED_SERVICE_STATS.issubset(second_names)
    both_service_stats = first_complete and second_complete

    points = 0.0
    points += 20 if score_present else 0
    points += 10 if current_game else 0
    points += 10 if server else 0
    points += 20 if point_by_point else 0
    points += 10 if statistics else 0
    points += 30 if both_service_stats else (15 if first_names or second_names else 0)
    confidence = min(points, 100.0)

    if score_present and current_game and server and point_by_point and both_service_stats:
        return FULL_STATS, confidence, "Live score, server, point-by-point data, and required service statistics are available for both players."
    if score_present and any((current_game, server, point_by_point, statistics)):
        missing = []
        if not current_game:
            missing.append("current game score")
        if not server:
            missing.append("server")
        if not point_by_point:
            missing.append("point-by-point data")
        if not both_service_stats:
            missing.append("complete service statistics for both players")
        return PARTIAL_STATS, confidence, "Matched, but missing " + ", ".join(missing) + "."
    if score_present:
        return SCORE_ONLY, confidence, "Only match/set score data is reliable enough to use."
    return PARTIAL_STATS, confidence, "Matched event has insufficient live scoring data."


def _candidate_score(
    pm_row: Mapping[str, Any],
    api_event: Mapping[str, Any],
    aliases: Mapping[str, str],
) -> Tuple[float, bool, str, Tuple[float, float]]:
    pm_players = [str(pm_row.get("player1") or ""), str(pm_row.get("player2") or "")]
    api_players = list(_api_players(api_event))
    pair, reversed_order, individual = _pair_score(pm_players, api_players, aliases)
    time_value, time_reason = _time_score(pm_row.get("event_start"), api_event)
    tournament_value, tournament_reason = _tournament_score(pm_row, api_event)

    # Names dominate. Time and tournament metadata are tie-breakers.
    total = pair * 0.76 + tournament_value * 0.18 + time_value * 0.06
    reason = (
        f"player similarity {individual[0] * 100:.0f}%/{individual[1] * 100:.0f}%; "
        f"{tournament_reason}; {time_reason}"
    )
    return total * 100, reversed_order, reason, individual


def reconcile_matches(
    polymarket_matches: Iterable[Dict[str, Any]],
    api_events: Iterable[Dict[str, Any]],
    aliases: Optional[Mapping[str, str]] = None,
    *,
    minimum_confidence: float = 82.0,
    ambiguity_margin: float = 6.0,
) -> List[ReconciliationRow]:
    alias_map = dict(aliases or load_aliases())
    api_list = [event for event in api_events if isinstance(event, dict) and is_supported_singles(event)]
    rows: List[ReconciliationRow] = []

    for pm_index, pm_row in enumerate(polymarket_matches):
        p1 = str(pm_row.get("player1") or "")
        p2 = str(pm_row.get("player2") or "")
        if not p1 or not p2:
            rows.append(
                ReconciliationRow(
                    polymarket_event_id=pm_row.get("event_id"),
                    polymarket_event_title=str(pm_row.get("event_title") or ""),
                    polymarket_market_id=pm_row.get("market_id"),
                    polymarket_market_title=str(pm_row.get("market_title") or ""),
                    player1=p1,
                    player2=p2,
                    api_event_key=None,
                    api_player1="",
                    api_player2="",
                    api_tournament="",
                    confidence=0.0,
                    match_status=UNMATCHED,
                    data_tier=UNMATCHED,
                    data_confidence=0.0,
                    reversed_order=False,
                    reason="Polymarket participants could not be extracted reliably.",
                    match_winner_market=bool(pm_row.get("match_winner_market")),
                    polymarket_score=pm_row.get("event_score"),
                    market_slug=pm_row.get("market_slug"),
                    market_confidence=float(pm_row.get("market_confidence") or 0.0),
                    source_index=pm_index,
                )
            )
            continue

        candidates: List[Tuple[float, bool, str, Tuple[float, float], int, Dict[str, Any]]] = []
        for api_index, api_event in enumerate(api_list):
            score, reversed_order, reason, individual = _candidate_score(pm_row, api_event, alias_map)
            candidates.append((score, reversed_order, reason, individual, api_index, api_event))
        candidates.sort(key=lambda item: item[0], reverse=True)

        best = candidates[0] if candidates else None
        second_score = candidates[1][0] if len(candidates) > 1 else 0.0
        if not best or best[0] < minimum_confidence:
            best_score = best[0] if best else 0.0
            best_reason = best[2] if best else "No API Tennis candidates were available."
            rows.append(
                ReconciliationRow(
                    polymarket_event_id=pm_row.get("event_id"),
                    polymarket_event_title=str(pm_row.get("event_title") or ""),
                    polymarket_market_id=pm_row.get("market_id"),
                    polymarket_market_title=str(pm_row.get("market_title") or ""),
                    player1=p1,
                    player2=p2,
                    api_event_key=None,
                    api_player1="",
                    api_player2="",
                    api_tournament="",
                    confidence=round(best_score, 1),
                    match_status=UNMATCHED,
                    data_tier=UNMATCHED,
                    data_confidence=0.0,
                    reversed_order=False,
                    reason=f"No candidate reached {minimum_confidence:.0f}% confidence. Best candidate: {best_reason}",
                    match_winner_market=bool(pm_row.get("match_winner_market")),
                    polymarket_score=pm_row.get("event_score"),
                    market_slug=pm_row.get("market_slug"),
                    market_confidence=float(pm_row.get("market_confidence") or 0.0),
                    source_index=pm_index,
                )
            )
            continue

        best_score, reversed_order, match_reason, individual, api_index, api_event = best
        if best_score - second_score < ambiguity_margin:
            api_p1, api_p2 = _api_players(api_event)
            tier, data_confidence, data_reason = classify_data_quality(api_event)
            rows.append(
                ReconciliationRow(
                    polymarket_event_id=pm_row.get("event_id"),
                    polymarket_event_title=str(pm_row.get("event_title") or ""),
                    polymarket_market_id=pm_row.get("market_id"),
                    polymarket_market_title=str(pm_row.get("market_title") or ""),
                    player1=p1,
                    player2=p2,
                    api_event_key=api_event.get("event_key"),
                    api_player1=api_p1,
                    api_player2=api_p2,
                    api_tournament=str(api_event.get("tournament_name") or ""),
                    confidence=round(best_score, 1),
                    match_status=AMBIGUOUS,
                    data_tier=UNMATCHED,
                    data_confidence=round(data_confidence, 1),
                    reversed_order=reversed_order,
                    reason=f"Ambiguous: top candidates are only {best_score - second_score:.1f} points apart. {match_reason} {data_reason}",
                    match_winner_market=bool(pm_row.get("match_winner_market")),
                    polymarket_score=pm_row.get("event_score"),
                    api_score=api_event.get("event_final_result"),
                    market_slug=pm_row.get("market_slug"),
                    market_confidence=float(pm_row.get("market_confidence") or 0.0),
                    source_index=pm_index,
                    api_index=api_index,
                )
            )
            continue

        # Both player similarities must be strong. This prevents a single famous
        # surname from forcing a false match.
        if min(individual) < 0.82:
            rows.append(
                ReconciliationRow(
                    polymarket_event_id=pm_row.get("event_id"),
                    polymarket_event_title=str(pm_row.get("event_title") or ""),
                    polymarket_market_id=pm_row.get("market_id"),
                    polymarket_market_title=str(pm_row.get("market_title") or ""),
                    player1=p1,
                    player2=p2,
                    api_event_key=None,
                    api_player1="",
                    api_player2="",
                    api_tournament="",
                    confidence=round(best_score, 1),
                    match_status=UNMATCHED,
                    data_tier=UNMATCHED,
                    data_confidence=0.0,
                    reversed_order=False,
                    reason=f"One player name was below the safe matching threshold. {match_reason}",
                    match_winner_market=bool(pm_row.get("match_winner_market")),
                    polymarket_score=pm_row.get("event_score"),
                    market_slug=pm_row.get("market_slug"),
                    market_confidence=float(pm_row.get("market_confidence") or 0.0),
                    source_index=pm_index,
                )
            )
            continue

        api_p1, api_p2 = _api_players(api_event)
        tier, data_confidence, data_reason = classify_data_quality(api_event)
        status = "MATCHED"
        if not pm_row.get("match_winner_market"):
            data_reason += " No match-winner market was identified in the event payload."
        rows.append(
            ReconciliationRow(
                polymarket_event_id=pm_row.get("event_id"),
                polymarket_event_title=str(pm_row.get("event_title") or ""),
                polymarket_market_id=pm_row.get("market_id"),
                polymarket_market_title=str(pm_row.get("market_title") or ""),
                player1=p1,
                player2=p2,
                api_event_key=api_event.get("event_key"),
                api_player1=api_p1,
                api_player2=api_p2,
                api_tournament=str(api_event.get("tournament_name") or ""),
                confidence=round(best_score, 1),
                match_status=status,
                data_tier=tier,
                data_confidence=round(data_confidence, 1),
                reversed_order=reversed_order,
                reason=f"{match_reason}. {data_reason}",
                match_winner_market=bool(pm_row.get("match_winner_market")),
                polymarket_score=pm_row.get("event_score"),
                api_score=api_event.get("event_final_result"),
                market_slug=pm_row.get("market_slug"),
                market_confidence=float(pm_row.get("market_confidence") or 0.0),
                source_index=pm_index,
                api_index=api_index,
            )
        )

    return rows


def coverage_summary(rows: Iterable[Any]) -> Dict[str, int]:
    items = list(rows)

    def value(row: Any, key: str) -> Any:
        return row.get(key) if isinstance(row, Mapping) else getattr(row, key, None)

    return {
        "polymarket_matches": len(items),
        "matched": sum(1 for row in items if value(row, "match_status") == "MATCHED"),
        "ambiguous": sum(1 for row in items if value(row, "match_status") == AMBIGUOUS),
        "full_stats": sum(1 for row in items if value(row, "data_tier") == FULL_STATS),
        "partial_stats": sum(1 for row in items if value(row, "data_tier") == PARTIAL_STATS),
        "score_only": sum(1 for row in items if value(row, "data_tier") == SCORE_ONLY),
        "unmatched": sum(1 for row in items if value(row, "data_tier") == UNMATCHED),
        "match_winner_markets": sum(1 for row in items if bool(value(row, "match_winner_market"))),
    }
