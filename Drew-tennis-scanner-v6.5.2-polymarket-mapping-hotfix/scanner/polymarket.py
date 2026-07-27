"""Read-only Polymarket US market discovery.

Version 6.0 uses this module for individual Polymarket lookups after API Tennis
has returned the live match list. Broad discovery helpers remain available for
diagnostics, but the Streamlit workflow is API Tennis first.

This module deliberately uses gateway.polymarket.us. No wallet, account, or
trading credentials are required.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

US_BASE = "https://gateway.polymarket.us"
DEFAULT_TIMEOUT = (5, 20)


class PolymarketUSError(RuntimeError):
    pass


@dataclass
class DiscoveryResult:
    """Result of a multi-source Polymarket tennis discovery pass."""

    matches: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    sources: Dict[str, int] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)


def _http_session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=2, connect=2, read=2, backoff_factor=0.3,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}), raise_on_status=False,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8))
    session.headers.update({"Accept": "application/json", "User-Agent": "DrewTennisScanner/6.1"})
    return session


def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    response = _http_session().get(
        f"{US_BASE}{path}",
        params=params or {},
        timeout=DEFAULT_TIMEOUT,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise PolymarketUSError("Polymarket US returned an unexpected response format.")
    return payload


def normalize_name(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9 ]+", " ", value).lower()
    return " ".join(value.split())


def _safe_bool(value: Any) -> Optional[bool]:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    if text in {"true", "1", "yes", "live", "open", "active", "in_progress", "in progress"}:
        return True
    if text in {"false", "0", "no", "closed", "ended", "finished", "final"}:
        return False
    return None


def _event_haystack(event: Dict[str, Any]) -> str:
    participants = event.get("participants") or []
    participant_text = " ".join(
        str(p.get("name") or p.get("title") or p) if isinstance(p, dict) else str(p)
        for p in participants
    )
    series = event.get("series") or event.get("league") or {}
    series_text = (
        " ".join(str(series.get(key) or "") for key in ("title", "name", "slug"))
        if isinstance(series, dict)
        else str(series)
    )
    return normalize_name(
        " ".join(
            [
                str(event.get("title", "")),
                str(event.get("subtitle", "")),
                str(event.get("description", "")),
                str(event.get("slug", "")),
                str(event.get("category", "")),
                str(event.get("subcategory", "")),
                str(event.get("seriesSlug", "")),
                series_text,
                participant_text,
            ]
        )
    )


def _is_tennis_event(event: Dict[str, Any]) -> bool:
    sources = [str(source) for source in (event.get("_discovery_sources") or [])]
    if "sport:tennis" in sources:
        return True
    for source in sources:
        normalized_source = normalize_name(source)
        if source.startswith("league:") and any(token in normalized_source for token in ("atp", "wta", "tennis", "challenger", "itf")):
            return True

    haystack = _event_haystack(event)
    explicit = normalize_name(
        " ".join(
            [
                str(event.get("sport") or ""),
                str(event.get("category") or ""),
                str(event.get("subcategory") or ""),
                str(event.get("seriesSlug") or ""),
            ]
        )
    )
    if "tennis" in explicit:
        return True
    tennis_tokens = (" atp ", " wta ", " challenger ", " itf ", " grand slam ")
    padded = f" {haystack} "
    return any(token in padded for token in tennis_tokens)


def _event_is_live(event: Dict[str, Any]) -> bool:
    if _safe_bool(event.get("ended")) is True:
        return False
    if _safe_bool(event.get("closed")) is True:
        return False
    if _safe_bool(event.get("live")) is True:
        return True

    state = event.get("eventState") or {}
    if isinstance(state, dict):
        state_text = normalize_name(
            " ".join(str(state.get(key) or "") for key in ("status", "state", "phase", "period"))
        )
        if any(token in state_text for token in ("live", "in progress", "playing", "started")):
            return True
        if any(token in state_text for token in ("ended", "finished", "final", "canceled", "cancelled")):
            return False

    period = normalize_name(str(event.get("period") or ""))
    if period and period not in {"final", "ended", "finished", "scheduled", "pregame", "pre game"}:
        return True

    # Last-resort fallback for feeds that omit `live` but include a non-empty score.
    score = str(event.get("score") or "").strip()
    if score and score not in {"0-0", "0 - 0", "-"} and _safe_bool(event.get("active")) is not False:
        return True
    return False


def _event_key(event: Dict[str, Any]) -> Tuple[str, str]:
    event_id = str(event.get("id") or event.get("eventId") or "").strip()
    slug = str(event.get("slug") or event.get("ticker") or "").strip()
    if event_id or slug:
        return event_id, slug
    return normalize_name(str(event.get("title") or "")), str(event.get("startTime") or event.get("startDate") or "")


def _dedupe_events(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    merged: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        key = _event_key(event)
        if key not in merged:
            merged[key] = dict(event)
            continue
        existing = merged[key]
        # Prefer the richer copy while preserving markets/participants from both.
        if len(str(event)) > len(str(existing)):
            primary, secondary = dict(event), existing
        else:
            primary, secondary = existing, event
        for collection_key in ("markets", "participants", "_discovery_sources"):
            combined: List[Any] = []
            seen = set()
            for item in list(primary.get(collection_key) or []) + list(secondary.get(collection_key) or []):
                marker = str(item.get("id") or item.get("slug") or item) if isinstance(item, dict) else str(item)
                if marker not in seen:
                    seen.add(marker)
                    combined.append(item)
            if combined:
                primary[collection_key] = combined
        merged[key] = primary
    return list(merged.values())


def _side_name(side: Any) -> str:
    """Return the participant name carried by a Retail API market side."""
    if not isinstance(side, dict):
        return str(side or "").strip()
    team = side.get("team") or {}
    if isinstance(team, dict):
        for key in ("name", "displayName", "safeName", "alias", "abbreviation"):
            value = str(team.get(key) or "").strip()
            if value:
                return value
    for key in ("name", "title", "outcome", "description", "identifier"):
        value = str(side.get(key) or "").strip()
        if value:
            return value
    return ""


def _market_sides(market: Dict[str, Any]) -> List[Any]:
    """Read current ``marketSides`` plus legacy side fields."""
    for key in ("marketSides", "sides", "outcomes"):
        value = market.get(key)
        if isinstance(value, list) and value:
            return value
    return []


def _extract_participant_names(event: Dict[str, Any]) -> List[str]:
    names: List[str] = []
    # `teams` replaced the deprecated `participants` field in June 2026.
    for participant in list(event.get("teams") or []) + list(event.get("participants") or []):
        if isinstance(participant, dict):
            name = participant.get("name") or participant.get("title") or participant.get("shortName")
            role = normalize_name(str(participant.get("role") or participant.get("type") or ""))
            if role and role not in {"player", "home", "away", "competitor", "participant", ""}:
                continue
        else:
            name = participant
        text = str(name or "").strip()
        if text and normalize_name(text) not in {normalize_name(existing) for existing in names}:
            names.append(text)

    if len(names) >= 2:
        return names[:2]

    # Current sports responses also carry the competitors on marketSides.
    for market in event.get("markets") or []:
        if not isinstance(market, dict):
            continue
        for side in _market_sides(market):
            name = _side_name(side)
            if name and normalize_name(name) not in {
                normalize_name(existing) for existing in names
            }:
                names.append(name)
        if len(names) >= 2:
            return names[:2]

    # Some event payloads encode the two players only in the title/subtitle.
    for source in (event.get("title"), event.get("subtitle")):
        text = str(source or "").strip()
        for pattern in (r"\s+vs\.?\s+", r"\s+v\.?\s+", r"\s+@\s+"):
            parts = re.split(pattern, text, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2:
                left, right = (part.strip(" -:|") for part in parts)
                if left and right:
                    return [left, right]
    return names[:2]


def _market_text(market: Dict[str, Any]) -> str:
    outcomes = _market_sides(market)
    outcome_text = " ".join(
        _side_name(side)
        for side in outcomes
    )
    return normalize_name(
        " ".join(
            [
                str(market.get("question") or ""),
                str(market.get("title") or ""),
                str(market.get("slug") or ""),
                str(market.get("marketType") or market.get("type") or ""),
                outcome_text,
            ]
        )
    )


def _match_winner_score(market: Dict[str, Any], players: Sequence[str]) -> int:
    text = _market_text(market)
    market_type = normalize_name(str(market.get("marketType") or market.get("type") or ""))
    score = 0
    if market_type in {"moneyline", "money line", "match winner", "winner", "win"}:
        score += 12
    if any(phrase in text for phrase in ("match winner", "to win match", "will win", "moneyline", "money line")):
        score += 10
    if "winner" in text or " win " in f" {text} ":
        score += 4

    normalized_players = [normalize_name(player) for player in players if player]
    surname_hits = 0
    full_hits = 0
    for player in normalized_players:
        if player and player in text:
            full_hits += 1
        surname = player.split()[-1] if player else ""
        if surname and surname in text:
            surname_hits += 1
    score += full_hits * 5 + surname_hits * 2

    # Exclude common non-moneyline tennis markets.
    exclusions = (
        "set winner",
        "game winner",
        "first set",
        "second set",
        "third set",
        "total games",
        "over ",
        "under ",
        "spread",
        "handicap",
        "exact score",
        "tiebreak",
        "tie break",
    )
    if any(term in text for term in exclusions):
        score -= 30
    return score


def _best_match_winner_market(event: Dict[str, Any], players: Sequence[str]) -> Tuple[Dict[str, Any], int]:
    markets = [market for market in (event.get("markets") or []) if isinstance(market, dict)]
    if not markets:
        return {}, 0
    ranked = sorted(((market, _match_winner_score(market, players)) for market in markets), key=lambda item: item[1], reverse=True)
    best_market, best_score = ranked[0]
    # A positive score is enough when the event itself clearly has two tennis players.
    if best_score > 0:
        return best_market, best_score
    return {}, best_score


def _build_match_row(event: Dict[str, Any]) -> Dict[str, Any]:
    players = _extract_participant_names(event)
    market, market_score = _best_match_winner_market(event, players)
    return {
        "event_id": event.get("id") or event.get("eventId"),
        "event_title": event.get("title") or event.get("subtitle"),
        "event_slug": event.get("slug"),
        "event_live": _event_is_live(event),
        "event_score": event.get("score"),
        "event_period": event.get("period"),
        "event_state": event.get("eventState"),
        "event_start": event.get("startTime") or event.get("startDate"),
        "game_id": event.get("gameId"),
        "sportradar_game_id": event.get("sportradarGameId"),
        "series_slug": event.get("seriesSlug") or (event.get("series") or {}).get("slug") if isinstance(event.get("series") or {}, dict) else event.get("seriesSlug"),
        "player1": players[0] if len(players) > 0 else "",
        "player2": players[1] if len(players) > 1 else "",
        "players_found": len(players) >= 2,
        "market_id": market.get("id"),
        "market_title": market.get("question") or market.get("title") or event.get("title"),
        "market_slug": market.get("slug") or event.get("slug"),
        "market_type": market.get("marketType") or market.get("type"),
        "match_winner_market": bool(market),
        "match_winner_score": market_score,
        "market_confidence": round(min(100.0, max(0.0, 45.0 + market_score * 2.0)), 1) if market else 0.0,
        "active": market.get("active", event.get("active")) if market else event.get("active"),
        "closed": market.get("closed", event.get("closed")) if market else event.get("closed"),
        "volume": (market.get("volumeNum") or market.get("volume") or event.get("volumeNum") or event.get("volume")) if market else (event.get("volumeNum") or event.get("volume")),
        "liquidity": (market.get("liquidityNum") or market.get("liquidity") or event.get("liquidityNum") or event.get("liquidity")) if market else (event.get("liquidityNum") or event.get("liquidity")),
        "sides": _market_sides(market) if market else [],
        "raw_event": event,
        "raw_market": market,
    }


def _flatten_events(events: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Backward-compatible one-row-per-market flattening used by manual search."""
    rows: List[Dict[str, Any]] = []
    seen = set()
    for event in events:
        markets = event.get("markets") or []
        if not markets:
            markets = [{}]
        for market in markets:
            players = _extract_participant_names(event)
            row = _build_match_row({**event, "markets": [market]})
            row["player1"] = players[0] if len(players) > 0 else row.get("player1", "")
            row["player2"] = players[1] if len(players) > 1 else row.get("player2", "")
            key = (row.get("market_id"), row.get("market_slug"), row.get("market_title"))
            if key not in seen:
                seen.add(key)
                rows.append(row)
    return rows


def _paginate_events(
    path: str,
    params: Optional[Dict[str, Any]] = None,
    *,
    limit: int = 50,
    max_pages: int = 10,
) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    base_params = dict(params or {})
    for page in range(max(1, max_pages)):
        offset = page * limit
        payload = _get(path, {**base_params, "limit": limit, "offset": offset})
        batch = payload.get("events") or []
        if not isinstance(batch, list) or not batch:
            break
        events.extend(event for event in batch if isinstance(event, dict))
        if len(batch) < limit:
            break
    return events


def search_us_markets(query: str, limit: int = 25, pages: int = 2) -> List[Dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return []
    events: List[Dict[str, Any]] = []
    for page in range(1, max(1, pages) + 1):
        payload = _get("/v1/search", {"query": query, "limit": limit, "page": page})
        batch = payload.get("events") or []
        if not isinstance(batch, list) or not batch:
            break
        events.extend(event for event in batch if isinstance(event, dict))
        if len(batch) < limit:
            break
    return _flatten_events(events)


def fetch_league_events(league: str, limit: int = 50, max_pages: int = 10) -> List[Dict[str, Any]]:
    """Fetch league events from the documented league endpoint."""
    normalized = str(league or "").strip().lower()
    if not normalized:
        return []
    events = _paginate_events(
        f"/v2/leagues/{normalized}/events",
        {"type": "sport", "section": "general"},
        limit=min(max(1, limit), 50),
        max_pages=max_pages,
    )
    return _flatten_events(events)


def fetch_atp_events(limit: int = 50) -> List[Dict[str, Any]]:
    return fetch_league_events("atp", limit=limit)


def fetch_wta_events(limit: int = 50) -> List[Dict[str, Any]]:
    return fetch_league_events("wta", limit=limit)


def fetch_all_leagues(limit: int = 50, max_pages: int = 10) -> List[Dict[str, Any]]:
    leagues: List[Dict[str, Any]] = []
    for page in range(max(1, max_pages)):
        offset = page * limit
        payload = _get("/v2/leagues", {"limit": min(limit, 50), "offset": offset})
        batch = payload.get("leagues") or []
        if not isinstance(batch, list) or not batch:
            break
        leagues.extend(row for row in batch if isinstance(row, dict))
        if len(batch) < limit:
            break
    return leagues


def _tennis_league_slugs(leagues: Iterable[Dict[str, Any]]) -> List[str]:
    slugs: List[str] = []
    for league in leagues:
        text = normalize_name(" ".join([str(league.get("name") or ""), str(league.get("slug") or "")]))
        padded = f" {text} "
        if any(token in padded for token in (" atp ", " wta ", " tennis ", " challenger ", " itf ")):
            slug = str(league.get("slug") or "").strip()
            if slug and slug not in slugs:
                slugs.append(slug)
    return slugs


def discover_live_tennis_matches(limit: int = 50, max_pages: int = 10) -> DiscoveryResult:
    """Discover all live tennis events using multiple documented endpoints.

    The sport-wide endpoint is primary. League, general live-event, and search
    endpoints are merged as coverage fallbacks. Every source is deduplicated by
    stable event ID/slug before filtering to live tennis events.
    """

    result = DiscoveryResult()
    collected: List[Dict[str, Any]] = []

    def collect(source: str, loader: Any) -> None:
        try:
            batch = loader()
            events = batch if isinstance(batch, list) else []
            result.sources[source] = len(events)
            for event in events:
                if not isinstance(event, dict):
                    continue
                tagged = dict(event)
                tagged["_discovery_sources"] = list(dict.fromkeys(list(tagged.get("_discovery_sources") or []) + [source]))
                collected.append(tagged)
        except (requests.RequestException, PolymarketUSError, ValueError, TypeError) as exc:
            result.sources[source] = 0
            result.errors.append(f"{source}: {exc}")

    collect(
        "sport:tennis",
        lambda: _paginate_events(
            "/v2/sports/tennis/events",
            {"type": "sport", "section": "general"},
            limit=min(max(1, limit), 50),
            max_pages=max_pages,
        ),
    )

    # The generic Events API is a useful fallback if the sport endpoint omits a
    # league or temporarily returns a partial page.
    collect(
        "events:live-sports",
        lambda: _paginate_events(
            "/v1/events",
            {"active": "true", "closed": "false", "live": "true", "categories": "sports"},
            limit=min(max(1, limit), 100),
            max_pages=max_pages,
        ),
    )

    try:
        leagues = fetch_all_leagues(limit=50, max_pages=max_pages)
        result.sources["leagues:index"] = len(leagues)
        for slug in _tennis_league_slugs(leagues):
            collect(
                f"league:{slug}",
                lambda slug=slug: _paginate_events(
                    f"/v2/leagues/{slug}/events",
                    {"type": "sport", "section": "general"},
                    limit=min(max(1, limit), 50),
                    max_pages=max_pages,
                ),
            )
    except (requests.RequestException, PolymarketUSError, ValueError, TypeError) as exc:
        result.sources["leagues:index"] = 0
        result.errors.append(f"leagues:index: {exc}")

    # Search is a final recall fallback. It is not the primary discovery path.
    try:
        search_rows = search_us_markets("tennis", limit=min(max(1, limit), 50), pages=min(max_pages, 5))
        search_events = [row.get("raw_event") for row in search_rows if isinstance(row.get("raw_event"), dict)]
        result.sources["search:tennis"] = len(search_events)
        for event in search_events:
            tagged = dict(event)
            tagged["_discovery_sources"] = list(dict.fromkeys(list(tagged.get("_discovery_sources") or []) + ["search:tennis"]))
            collected.append(tagged)
    except (requests.RequestException, PolymarketUSError, ValueError, TypeError) as exc:
        result.sources["search:tennis"] = 0
        result.errors.append(f"search:tennis: {exc}")

    deduped = _dedupe_events(collected)
    live_tennis = [event for event in deduped if _is_tennis_event(event) and _event_is_live(event)]
    result.events = live_tennis
    result.matches = [_build_match_row(event) for event in live_tennis]
    result.matches.sort(key=lambda row: (str(row.get("event_start") or ""), str(row.get("event_title") or "")))
    return result


def _candidate_identity(row: Dict[str, Any]) -> Tuple[Any, Any, Any]:
    return row.get("market_id"), row.get("market_slug"), row.get("market_title")


def _player_match_score(expected: str, candidate: str) -> float:
    """Initial/surname-aware similarity without requiring exact full names."""
    left, right = normalize_name(expected), normalize_name(candidate)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    left_tokens, right_tokens = left.split(), right.split()
    left_last, right_last = left_tokens[-1], right_tokens[-1]
    if left_last != right_last:
        return 0.0
    if len(left_tokens) == 1 or len(right_tokens) == 1:
        return 0.86
    left_first, right_first = left_tokens[0], right_tokens[0]
    if left_first == right_first:
        return 0.98
    if left_first[:1] == right_first[:1]:
        return 0.94
    return 0.58


def _row_player_pair_score(row: Dict[str, Any], player1: str, player2: str) -> float:
    rp1, rp2 = str(row.get("player1") or ""), str(row.get("player2") or "")
    direct = (_player_match_score(player1, rp1) + _player_match_score(player2, rp2)) / 2
    reverse = (_player_match_score(player1, rp2) + _player_match_score(player2, rp1)) / 2
    explicit = max(direct, reverse)

    text = normalize_name(" ".join([
        str(row.get("event_title") or ""), str(row.get("market_title") or ""),
        str(row.get("event_slug") or ""), str(row.get("market_slug") or ""),
    ]))
    surnames = [normalize_name(player).split()[-1] for player in (player1, player2) if normalize_name(player)]
    text_score = 0.0
    if len(surnames) == 2 and all(surname in text for surname in surnames):
        text_score = 0.89
    return max(explicit, text_score)


def _tournament_similarity(expected: Optional[str], row: Dict[str, Any]) -> float:
    expected_text = normalize_name(str(expected or ""))
    if not expected_text:
        return 0.0
    candidate = normalize_name(" ".join([
        str(row.get("event_title") or ""), str(row.get("event_slug") or ""),
        str(row.get("series_slug") or ""), str((row.get("raw_event") or {}).get("subtitle") or ""),
    ]))
    if expected_text and expected_text in candidate:
        return 1.0
    expected_tokens = {token for token in expected_text.split() if len(token) > 2 and token not in {"itf", "men", "women", "singles", "challenger", "atp", "wta"}}
    candidate_tokens = set(candidate.split())
    if not expected_tokens:
        return 0.0
    return len(expected_tokens & candidate_tokens) / len(expected_tokens)


def match_tennis_market(
    player1: str,
    player2: str,
    league: Optional[str] = None,
    competition_group: Optional[str] = None,
    tournament: Optional[str] = None,
    event_start: Optional[str] = None,
    *,
    search_pages: int = 2,
    include_sport_fallback: bool = True,
) -> List[Dict[str, Any]]:
    """Find the Polymarket counterpart for one API Tennis match.

    The lookup escalates only when needed. A normal exact-pair hit usually costs
    one or two search requests; broader surname, player, league, and sport calls
    are fallbacks rather than unconditional work. This keeps Streamlit responsive.
    """
    if not str(player1 or "").strip() or not str(player2 or "").strip():
        return []

    p1, p2 = normalize_name(player1), normalize_name(player2)
    s1 = p1.split()[-1] if p1 else ""
    s2 = p2.split()[-1] if p2 else ""
    candidates: List[Dict[str, Any]] = []
    seen = set()

    def add(rows: Iterable[Dict[str, Any]], source: str) -> None:
        for row in rows:
            if not isinstance(row, dict):
                continue
            identity = _candidate_identity(row)
            if identity in seen:
                continue
            seen.add(identity)
            copy = dict(row)
            copy["lookup_source"] = source
            candidates.append(copy)

    def best_pair_score() -> float:
        return max((_row_player_pair_score(row, player1, player2) for row in candidates), default=0.0)

    def search(query: str, pages: int) -> None:
        if not query.strip():
            return
        try:
            add(search_us_markets(query, limit=30, pages=max(1, pages)), f"search:{query}")
        except (requests.RequestException, PolymarketUSError, ValueError, TypeError):
            pass

    # Fast path: the exact pair normally finds the market immediately.
    search(f"{player1} {player2}", min(max(1, search_pages), 2))
    if best_pair_score() < 0.88:
        search(f"{player2} {player1}", 1)
    if best_pair_score() < 0.88 and s1 and s2:
        search(f"{s1} {s2}", 2)
    if best_pair_score() < 0.82:
        search(player1, 1)
        if best_pair_score() < 0.82:
            search(player2, 1)

    normalized_group = str(competition_group or "").strip().upper()
    normalized_league = str(league or "").strip().lower()
    if best_pair_score() < 0.82 and normalized_league in {"atp", "wta"} and normalized_group in {"TOUR", "CHALLENGER"}:
        try:
            add(fetch_league_events(normalized_league, limit=50, max_pages=3), f"league:{normalized_league}")
        except (requests.RequestException, PolymarketUSError, ValueError, TypeError):
            pass

    # ITF markets are not guaranteed to sit under an ATP/WTA league slug, so the
    # sport endpoint is the final recall fallback when searches did not find both players.
    if best_pair_score() < 0.82 and include_sport_fallback:
        try:
            sport_events = _paginate_events(
                "/v2/sports/tennis/events",
                {"type": "sport", "section": "general"},
                limit=50,
                max_pages=4,
            )
            add(_flatten_events(sport_events), "sport:tennis")
        except (requests.RequestException, PolymarketUSError, ValueError, TypeError):
            pass

    ranked: List[Tuple[float, Dict[str, Any]]] = []
    for row in candidates:
        pair = _row_player_pair_score(row, player1, player2)
        if pair < 0.72:
            continue
        market_bonus = 0.06 if row.get("match_winner_market") else 0.0
        live_bonus = 0.03 if row.get("event_live") else 0.0
        tournament_similarity = _tournament_similarity(tournament, row)
        tournament_bonus = 0.06 * tournament_similarity
        score = min(1.0, pair * 0.86 + market_bonus + live_bonus + tournament_bonus)
        row["api_match_confidence"] = round(score * 100, 1)
        row["api_pair_similarity"] = round(pair * 100, 1)
        row["api_tournament_similarity"] = round(tournament_similarity * 100, 1)
        ranked.append((score, row))

    ranked.sort(
        key=lambda item: (
            item[0],
            bool(item[1].get("match_winner_market")),
            bool(item[1].get("event_live")),
            float(item[1].get("volume") or 0),
        ),
        reverse=True,
    )
    return [row for _, row in ranked]

def get_bbo(market_slug: str) -> Dict[str, Any]:
    if not market_slug:
        return {}
    try:
        return _get(f"/v1/markets/{market_slug}/bbo")
    except (requests.RequestException, PolymarketUSError, ValueError, TypeError):
        return {}


def get_market_by_slug(market_slug: str) -> Dict[str, Any]:
    """Fetch the richer public market payload used for price/volume display."""
    if not market_slug:
        return {}
    try:
        payload = _get(f"/v1/market/slug/{market_slug}")
    except (requests.RequestException, PolymarketUSError, ValueError, TypeError):
        return {}
    for key in ("market", "data", "result"):
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, dict):
            return value
    return payload if isinstance(payload, dict) else {}


def _unwrap_number(value: Any) -> Optional[float]:
    if isinstance(value, dict):
        for key in ("value", "px", "price", "amount"):
            if key in value:
                return _unwrap_number(value.get(key))
        return None
    if value in (None, ""):
        return None
    try:
        number = float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None
    return number if number == number else None


def _to_cents(value: Any) -> Optional[float]:
    number = _unwrap_number(value)
    if number is None or number < 0:
        return None
    # Gateway prices normally use 0..1 decimals, while some search payloads
    # already report cents. Preserve either representation without guessing.
    if number <= 1.0:
        number *= 100.0
    if number > 100.0:
        return None
    return round(number, 2)


def _first_number(sources: Sequence[Dict[str, Any]], keys: Sequence[str]) -> Optional[float]:
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in keys:
            number = _unwrap_number(source.get(key))
            if number is not None:
                return number
    return None


def extract_market_metrics(row: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Extract informational market price, volume, and liquidity robustly."""
    raw_market = row.get("raw_market") if isinstance(row.get("raw_market"), dict) else {}
    details = row.get("market_details") if isinstance(row.get("market_details"), dict) else {}
    raw_event = row.get("raw_event") if isinstance(row.get("raw_event"), dict) else {}
    nested = details.get("marketData") if isinstance(details.get("marketData"), dict) else {}
    sources = [nested, details, raw_market, row, raw_event]

    price: Optional[float] = None
    for source in sources:
        for key in (
            "bestAsk", "bestOffer", "currentPx", "currentPrice", "lastTradePrice",
            "lastTradePx", "yesPrice", "outcomePrice", "price", "lastPrice", "bestBid",
        ):
            price = _to_cents(source.get(key)) if isinstance(source, dict) else None
            if price is not None:
                break
        if price is not None:
            break

    if price is None:
        sides = row.get("sides") or raw_market.get("sides") or raw_market.get("outcomes") or []
        for side in sides if isinstance(sides, list) else []:
            if not isinstance(side, dict):
                continue
            for key in ("bestAsk", "price", "lastPrice", "lastTradePrice", "outcomePrice"):
                price = _to_cents(side.get(key))
                if price is not None:
                    break
            if price is not None:
                break

    volume = _first_number(
        sources,
        ("volumeNum", "volume", "volume24hr", "volume24h", "sharesTraded"),
    )
    liquidity = _first_number(
        sources,
        ("liquidityNum", "liquidity", "openInterest", "open_interest"),
    )
    return {
        "price_cents": price,
        "volume": round(volume, 2) if volume is not None else None,
        "liquidity": round(liquidity, 2) if liquidity is not None else None,
    }


def extract_display_price(row: Dict[str, Any]) -> Optional[float]:
    return extract_market_metrics(row).get("price_cents")


def extract_bbo_prices(payload: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Return long/YES and short/NO executable estimates in cents."""
    if not isinstance(payload, dict):
        payload = {}
    data = payload.get("marketData") if isinstance(payload.get("marketData"), dict) else payload

    def amount(*names: str) -> Optional[float]:
        for name in names:
            value = _to_cents(data.get(name))
            if value is not None:
                return value
        return None

    best_ask = amount("bestAsk", "bestOffer", "ask")
    best_bid = amount("bestBid", "bid")
    current = amount("currentPx", "currentPrice", "price")
    last = amount("lastTradePx", "lastTradePrice", "lastPrice")
    return {
        "long_buy_cents": best_ask if best_ask is not None else current if current is not None else last,
        "short_buy_cents": round(100 - best_bid, 2) if best_bid is not None else None,
        "best_bid_cents": best_bid,
        "best_ask_cents": best_ask,
        "current_cents": current,
        "last_trade_cents": last,
    }


def enrich_market_row(row: Dict[str, Any], *, include_bbo: bool = True) -> Dict[str, Any]:
    """Return a copy enriched with live public metadata and BBO values."""
    enriched = dict(row)
    slug = str(enriched.get("market_slug") or "").strip()
    details = get_market_by_slug(slug) if slug else {}
    if details:
        enriched["market_details"] = details
        existing_market = enriched.get("raw_market") if isinstance(enriched.get("raw_market"), dict) else {}
        enriched["raw_market"] = {**existing_market, **details}
        enriched["sides"] = _market_sides(details) or enriched.get("sides") or []
    bbo_payload = get_bbo(slug) if include_bbo and slug else {}
    bbo = extract_bbo_prices(bbo_payload)
    metrics = extract_market_metrics(enriched)
    display_price = bbo.get("long_buy_cents") or metrics.get("price_cents")
    enriched.update(
        {
            "display_price_cents": display_price,
            "best_bid_cents": bbo.get("best_bid_cents"),
            "best_ask_cents": bbo.get("best_ask_cents"),
            "current_cents": bbo.get("current_cents"),
            "last_trade_cents": bbo.get("last_trade_cents"),
            "volume": metrics.get("volume"),
            "liquidity": metrics.get("liquidity"),
            "bbo_payload": bbo_payload,
            "market_data_timestamp": datetime.now(timezone.utc).isoformat(),
        }
    )
    return enriched


def infer_player_market_side(
    row: Dict[str, Any],
    player: str,
    opponent: str,
) -> Optional[str]:
    """Infer whether a player is the Long/YES or Short/NO side conservatively."""
    player_name = normalize_name(player)
    opponent_name = normalize_name(opponent)
    player_surname = player_name.split()[-1] if player_name else ""
    opponent_surname = opponent_name.split()[-1] if opponent_name else ""

    raw_market = row.get("raw_market") or {}
    sides = (
        row.get("sides")
        or _market_sides(raw_market if isinstance(raw_market, dict) else {})
        or []
    )

    # Current Polymarket US sports markets explicitly identify which player is
    # long and short through marketSides[].team and marketSides[].long.
    structured: List[Tuple[str, bool]] = []
    for side in sides:
        if not isinstance(side, dict) or not isinstance(side.get("long"), bool):
            continue
        label = _side_name(side)
        if label:
            structured.append((label, bool(side["long"])))
    if len(structured) >= 2:
        player_matches = [
            (label, is_long, _player_match_score(player, label))
            for label, is_long in structured
        ]
        opponent_matches = [
            (label, is_long, _player_match_score(opponent, label))
            for label, is_long in structured
        ]
        best_player = max(player_matches, key=lambda item: item[2])
        best_opponent = max(opponent_matches, key=lambda item: item[2])
        if (
            best_player[2] >= 0.86
            and best_opponent[2] >= 0.86
            and best_player[0] != best_opponent[0]
        ):
            return "Long / YES" if best_player[1] else "Short / NO"

    normalized_sides: List[str] = []
    for side in sides:
        normalized_sides.append(normalize_name(_side_name(side)))

    if len(normalized_sides) >= 2:
        first, second = normalized_sides[0], normalized_sides[1]
        first_matches_player = bool(player_name and player_name in first) or bool(player_surname and player_surname in first)
        second_matches_player = bool(player_name and player_name in second) or bool(player_surname and player_surname in second)
        first_matches_opponent = bool(opponent_name and opponent_name in first) or bool(opponent_surname and opponent_surname in first)
        second_matches_opponent = bool(opponent_name and opponent_name in second) or bool(opponent_surname and opponent_surname in second)
        if first_matches_player and second_matches_opponent and not second_matches_player:
            return "Long / YES"
        if second_matches_player and first_matches_opponent and not first_matches_player:
            return "Short / NO"

    market_text = normalize_name(
        " ".join(
            [
                str(row.get("market_title") or ""),
                str(raw_market.get("question") or ""),
                str(raw_market.get("title") or ""),
            ]
        )
    )
    player_hit = bool(player_name and player_name in market_text)
    opponent_hit = bool(opponent_name and opponent_name in market_text)
    if not player_hit and player_surname:
        player_hit = player_surname in market_text
    if not opponent_hit and opponent_surname:
        opponent_hit = opponent_surname in market_text
    if player_hit and not opponent_hit:
        return "Long / YES"
    if opponent_hit and not player_hit:
        return "Short / NO"
    return None


def infer_player_prices(
    row: Dict[str, Any],
    player1: str,
    player2: str,
    bbo_prices: Dict[str, Any],
    metadata_price: Optional[float] = None,
) -> Dict[str, Any]:
    """Return informational price estimates for both players when inference is safe."""
    player1_side = infer_player_market_side(row, player1, player2)
    player2_side = infer_player_market_side(row, player2, player1)
    long_price = bbo_prices.get("long_buy_cents")
    short_price = bbo_prices.get("short_buy_cents")
    if long_price is None:
        long_price = metadata_price
    prices: Dict[str, float] = {}
    sides: Dict[str, Optional[str]] = {player1: player1_side, player2: player2_side}
    for player, side in sides.items():
        candidate = long_price if side == "Long / YES" else short_price if side == "Short / NO" else None
        try:
            if candidate is not None:
                prices[player] = round(float(candidate), 2)
        except (TypeError, ValueError):
            pass
    return {"prices": prices, "sides": sides, "complete": player1 in prices and player2 in prices}
