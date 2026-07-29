from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BASE_URL = "https://api.api-tennis.com/tennis/"
VALID_RANKING_TOURS = {"ATP", "WTA"}
DEFAULT_TIMEOUT: Tuple[float, float] = (5.0, 25.0)


class APITennisError(RuntimeError):
    pass


@dataclass
class LiveSnapshot:
    events: List[Dict[str, Any]] = field(default_factory=list)
    livescore_count: int = 0
    fixtures_live_count: int = 0
    duplicates_removed: int = 0
    duration_seconds: float = 0.0
    timezone: str = "America/Phoenix"
    warnings: List[str] = field(default_factory=list)
    source_by_event_key: Dict[str, str] = field(default_factory=dict)
    fixture_events: List[Dict[str, Any]] = field(default_factory=list, repr=False)

    def summary(self) -> Dict[str, Any]:
        return {
            "events": len(self.events),
            "livescore_count": self.livescore_count,
            "fixtures_live_count": self.fixtures_live_count,
            "duplicates_removed": self.duplicates_removed,
            "duration_seconds": round(self.duration_seconds, 2),
            "timezone": self.timezone,
            "warnings": list(self.warnings),
        }


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2,
        connect=2,
        read=2,
        backoff_factor=0.35,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8))
    session.headers.update({"Accept": "application/json", "User-Agent": "DrewTennisScanner/6.5.9.1"})
    return session


def _request(api_key: str, method: str, **params: Any) -> Any:
    if not str(api_key or "").strip():
        raise ValueError("API Tennis key is missing.")

    clean_params = {"method": method, "APIkey": api_key}
    clean_params.update({key: value for key, value in params.items() if value not in (None, "")})

    try:
        response = _session().get(BASE_URL, params=clean_params, timeout=DEFAULT_TIMEOUT)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise APITennisError(f"API Tennis {method} request failed: {exc}") from exc

    try:
        payload = response.json()
    except ValueError as exc:
        preview = response.text[:180].replace("\n", " ")
        raise APITennisError(f"API Tennis {method} returned invalid JSON: {preview}") from exc

    if not isinstance(payload, dict):
        raise APITennisError(f"API Tennis {method} returned an unexpected payload type.")
    if str(payload.get("success")) not in {"1", "True", "true"} and payload.get("success") is not True:
        error = payload.get("error") or payload.get("message") or f"API Tennis {method} request failed."
        raise APITennisError(str(error))
    return payload.get("result", [])


def _coerce_rows(result: Any) -> List[Dict[str, Any]]:
    """Normalize provider list/dictionary response variants into event rows."""
    if isinstance(result, list):
        return [row for row in result if isinstance(row, dict)]
    if isinstance(result, dict):
        for key in ("events", "fixtures", "items", "data", "results"):
            nested = result.get(key)
            if isinstance(nested, list):
                return [row for row in nested if isinstance(row, dict)]
        # Some API versions key results by event/player ID.
        values = [row for row in result.values() if isinstance(row, dict)]
        if values:
            return values
    return []


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return str(value or "").strip().lower() in {"1", "true", "yes", "live", "in progress", "in_progress"}


def _looks_live(event: Dict[str, Any]) -> bool:
    raw_live = event.get("event_live")
    if raw_live not in (None, ""):
        if _truthy(raw_live):
            return True
        if str(raw_live).strip().lower() in {"0", "false", "no", "off"}:
            return False
    status = str(event.get("event_status") or "").strip().lower()
    if any(token in status for token in ("set", "game", "tiebreak", "tie break", "live", "in progress")):
        return True
    return False


def _event_key(event: Dict[str, Any], fallback_index: int = 0) -> str:
    return str(event.get("event_key") or event.get("match_key") or f"unknown-{fallback_index}")


def _richness(event: Dict[str, Any]) -> Tuple[int, int, int]:
    return (
        len(event.get("statistics") or []),
        len(event.get("pointbypoint") or []),
        len(str(event)),
    )


def _merge_event(existing: Dict[str, Any], incoming: Dict[str, Any]) -> Dict[str, Any]:
    primary, secondary = (incoming, existing) if _richness(incoming) > _richness(existing) else (existing, incoming)
    merged = dict(primary)
    for key, value in secondary.items():
        if merged.get(key) in (None, "", [], {}):
            merged[key] = value
    return merged


def deduplicate_events(events: Iterable[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], int]:
    by_key: Dict[str, Dict[str, Any]] = {}
    duplicates = 0
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            continue
        key = _event_key(event, index)
        if key in by_key:
            by_key[key] = _merge_event(by_key[key], event)
            duplicates += 1
        else:
            by_key[key] = dict(event)
    return list(by_key.values()), duplicates


def get_live_events(
    api_key: str,
    *,
    timezone: str = "America/Phoenix",
    event_type_key: Optional[str] = None,
    tournament_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    result = _request(
        api_key,
        "get_livescore",
        timezone=timezone,
        event_type_key=event_type_key,
        tournament_key=tournament_key,
    )
    return _coerce_rows(result)


def get_fixtures(
    api_key: str,
    date_start: str,
    date_stop: Optional[str] = None,
    *,
    timezone: str = "America/Phoenix",
) -> List[Dict[str, Any]]:
    result = _request(
        api_key,
        "get_fixtures",
        date_start=date_start,
        date_stop=date_stop or date_start,
        timezone=timezone,
    )
    return _coerce_rows(result)


def get_live_snapshot(
    api_key: str,
    *,
    timezone: str = "America/Phoenix",
    include_live_fixtures_fallback: bool = True,
    local_date: Optional[str] = None,
) -> LiveSnapshot:
    """Return a complete, deduplicated live snapshot without filtering match types.

    `get_livescore` remains the primary source. A same-day `get_fixtures` pass is
    merged only for rows that themselves look live. This catches occasional
    provider timing gaps while avoiding scheduled matches in the live scanner.
    """

    started = time.perf_counter()
    snapshot = LiveSnapshot(timezone=timezone)
    livescore_events = get_live_events(api_key, timezone=timezone)
    snapshot.livescore_count = len(livescore_events)

    tagged: List[Dict[str, Any]] = []
    for event in livescore_events:
        row = dict(event)
        row["_api_source"] = "get_livescore"
        tagged.append(row)
        snapshot.source_by_event_key[_event_key(row)] = "get_livescore"

    if include_live_fixtures_fallback:
        if local_date:
            date_value = local_date
        else:
            try:
                date_value = datetime.now(ZoneInfo(timezone)).date().isoformat()
            except Exception:
                date_value = datetime.now().date().isoformat()
        try:
            fixture_rows = get_fixtures(api_key, date_value, timezone=timezone)
            snapshot.fixture_events = [dict(row) for row in fixture_rows if isinstance(row, dict)]
            live_fixture_rows = [row for row in fixture_rows if _looks_live(row)]
            snapshot.fixtures_live_count = len(live_fixture_rows)
            for event in live_fixture_rows:
                row = dict(event)
                row["_api_source"] = "get_fixtures_live_fallback"
                tagged.append(row)
                snapshot.source_by_event_key.setdefault(_event_key(row), "get_fixtures_live_fallback")
        except Exception as exc:  # fallback must never prevent the primary live list
            snapshot.warnings.append(f"Fixtures fallback was unavailable: {exc}")

    snapshot.events, snapshot.duplicates_removed = deduplicate_events(tagged)
    snapshot.events.sort(
        key=lambda event: (
            str(event.get("event_type_type") or ""),
            str(event.get("tournament_name") or ""),
            str(event.get("event_time") or ""),
            str(event.get("event_first_player") or ""),
        )
    )
    snapshot.duration_seconds = time.perf_counter() - started
    return snapshot


def get_event_types(api_key: str) -> List[Dict[str, Any]]:
    result = _request(api_key, "get_events")
    return _coerce_rows(result)


def get_rankings(api_key: str, tour: str) -> Dict[str, int]:
    normalized_tour = str(tour or "").strip().upper()
    if normalized_tour not in VALID_RANKING_TOURS:
        raise ValueError("Ranking tour must be ATP or WTA.")

    result = _request(api_key, "get_standings", event_type=normalized_tour)
    rankings: Dict[str, int] = {}
    for row in _coerce_rows(result):
        if not isinstance(row, dict):
            continue
        player_key, place = row.get("player_key"), row.get("place")
        if player_key is None or place is None:
            continue
        try:
            rankings[str(player_key)] = int(float(place))
        except (TypeError, ValueError):
            continue
    return rankings


def get_atp_rankings(api_key: str) -> Dict[str, int]:
    return get_rankings(api_key, "ATP")


def get_wta_rankings(api_key: str) -> Dict[str, int]:
    return get_rankings(api_key, "WTA")


def summarize_live_event(event: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "event_key": _event_key(event),
        "player1": event.get("event_first_player") or "Unknown",
        "player2": event.get("event_second_player") or "Unknown",
        "tournament": event.get("tournament_name") or "",
        "score": event.get("event_final_result") or "0 - 0",
        "game_score": event.get("event_game_result") or "0 - 0",
        "status": event.get("event_status") or "Live",
        "event_type": event.get("event_type_type") or "Unknown",
        "serving": event.get("event_serve") or "Unknown",
        "first_player_key": event.get("first_player_key"),
        "second_player_key": event.get("second_player_key"),
        "source": event.get("_api_source") or "get_livescore",
        "statistics_count": len(event.get("statistics") or []),
        "pointbypoint_count": len(event.get("pointbypoint") or []),
        "scores_count": len(event.get("scores") or []),
    }
