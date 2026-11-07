"""Shared validation for Polymarket US tennis match-winner markets.

The scanner is designed to trade only the ordinary match-winner moneyline.
Tennis exact-score, set, game, spread, total, and proposition markets are never
valid execution targets, even when they contain both player names.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping
from typing import Any

MONEYLINE_V2 = "SPORTS_MARKET_TYPE_MONEYLINE"
UNSPECIFIED_V2 = {
    "UNKNOWN",
    "UNSPECIFIED",
    "SPORTS_MARKET_TYPE_UNKNOWN",
    "SPORTS_MARKET_TYPE_UNSPECIFIED",
}
NON_MONEYLINE_V2 = {
    "SPORTS_MARKET_TYPE_SPREAD",
    "SPORTS_MARKET_TYPE_TOTAL",
    "SPORTS_MARKET_TYPE_PROP",
}


def normalize_market_text(value: Any) -> str:
    ascii_text = (
        unicodedata.normalize("NFKD", str(value or ""))
        .encode("ascii", "ignore")
        .decode()
    )
    return " ".join(re.sub(r"[^a-zA-Z0-9 ]+", " ", ascii_text).lower().split())


def market_question(market: Mapping[str, Any]) -> str:
    """Return the most useful human-facing market label."""
    for key in ("question", "title", "subtitle", "description", "slug"):
        value = str(market.get(key) or "").strip()
        if value:
            return value
    return ""


def sports_market_type(market: Mapping[str, Any]) -> str:
    """Return the best available sports market type without normalizing it."""
    for key in ("sportsMarketTypeV2", "sportsMarketType"):
        value = str(market.get(key) or "").strip()
        if value:
            return value
    return ""


def _side_text(market: Mapping[str, Any]) -> str:
    values: list[str] = []
    raw_sides = market.get("marketSides") or market.get("sides") or market.get("outcomes") or []
    if not isinstance(raw_sides, list):
        return ""
    for side in raw_sides:
        if isinstance(side, Mapping):
            team = side.get("team")
            if isinstance(team, Mapping):
                values.extend(
                    str(team.get(key) or "")
                    for key in ("name", "displayName", "safeName", "alias", "abbreviation")
                )
            values.extend(
                str(side.get(key) or "")
                for key in (
                    "name",
                    "title",
                    "description",
                    "identifier",
                    "outcome",
                    "displayName",
                    "safeName",
                    "alias",
                    "abbreviation",
                )
            )
        else:
            values.append(str(side or ""))
    return " ".join(values)


def _coerce_long_flag(side: Mapping[str, Any]) -> bool | None:
    """Read current and legacy LONG/SHORT indicators from a market side."""
    value = side.get("long")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    normalized = normalize_market_text(value)
    if normalized in {"true", "yes", "long", "buy long"}:
        return True
    if normalized in {"false", "no", "short", "buy short"}:
        return False
    for key in ("side", "position", "contractSide", "outcomeType", "outcome"):
        normalized = normalize_market_text(side.get(key))
        if normalized in {"long", "yes", "affirmative"}:
            return True
        if normalized in {"short", "no", "negative"}:
            return False
    return None


def _competitor_name(side: Mapping[str, Any]) -> str:
    """Return a real competitor label, not a generic YES/NO outcome label."""
    team = side.get("team")
    sources = [team] if isinstance(team, Mapping) else []
    sources.append(side)
    for source in sources:
        for key in (
            "name",
            "displayName",
            "safeName",
            "alias",
            "abbreviation",
            "title",
        ):
            value = str(source.get(key) or "").strip()
            normalized = normalize_market_text(value)
            if value and normalized not in {
                "yes",
                "no",
                "long",
                "short",
                "home",
                "away",
            }:
                return value
    return ""


def has_binary_named_competitor_sides(market: Mapping[str, Any]) -> bool:
    """Return True for a binary market with two named, opposite competitors.

    Current Polymarket US tennis payloads do not always include a sports market
    type or a question containing the words "match winner". The authenticated
    sports payload still exposes a stronger structural signal: exactly one LONG
    and one SHORT contract, each attached to a different named player. This is
    accepted only after all exact-score/set/prop signatures have been rejected.
    """
    raw_sides = (
        market.get("marketSides")
        or market.get("sides")
        or market.get("outcomes")
        or []
    )
    if not isinstance(raw_sides, list) or len(raw_sides) != 2:
        return False

    parsed: list[tuple[bool, str]] = []
    for raw_side in raw_sides:
        if not isinstance(raw_side, Mapping):
            return False
        long_flag = _coerce_long_flag(raw_side)
        competitor = _competitor_name(raw_side)
        if long_flag is None or not competitor:
            return False
        parsed.append((long_flag, normalize_market_text(competitor)))

    return (
        {long_flag for long_flag, _name in parsed} == {True, False}
        and parsed[0][1] != parsed[1][1]
    )


def market_validation_text(market: Mapping[str, Any]) -> str:
    return normalize_market_text(
        " ".join(
            [
                str(market.get("question") or ""),
                str(market.get("title") or ""),
                str(market.get("subtitle") or ""),
                str(market.get("description") or ""),
                str(market.get("slug") or ""),
                str(market.get("sportsMarketTypeV2") or ""),
                str(market.get("sportsMarketType") or ""),
                str(market.get("marketType") or market.get("type") or ""),
                _side_text(market),
            ]
        )
    )


def has_non_moneyline_signature(market: Mapping[str, Any]) -> bool:
    """Detect exact-score and other tennis side markets from metadata/text/slug."""
    v2 = str(market.get("sportsMarketTypeV2") or "").strip().upper()
    if v2 in NON_MONEYLINE_V2:
        return True

    text = market_validation_text(market)
    exclusions = (
        "set winner",
        "game winner",
        "first set",
        "second set",
        "third set",
        "fourth set",
        "fifth set",
        "total games",
        "total sets",
        "over ",
        "under ",
        "spread",
        "handicap",
        "exact score",
        "correct score",
        "set score",
        "sets score",
        "tiebreak",
        "tie break",
        "player prop",
        "match prop",
        "straight sets",
        "set betting",
        "match score",
        "winning margin",
    )
    if any(term in text for term in exclusions):
        return True

    # Handles labels such as "Musetti wins 2-0" after punctuation normalization.
    if re.search(r"\b(?:win|wins|winning)\s+\d+\s+\d+\b", text):
        return True

    raw_label = " ".join(
        str(market.get(key) or "")
        for key in ("question", "title", "subtitle", "description")
    )
    # Catch exact-score wording even when a provider omitted the sports type.
    if re.search(
        r"\b(?:win|wins|winning|defeat|defeats|beat|beats|score|result|sets?)\b"
        r".{0,24}\b[0-5]\s*[-:]\s*[0-5]\b",
        raw_label,
        flags=re.IGNORECASE,
    ):
        return True
    if re.search(
        r"\b(?:win|wins|winning|defeat|defeats|beat|beats)\b"
        r".{0,18}\b[0-5]\s+(?:sets?\s+to\s+)?[0-5]\b",
        raw_label,
        flags=re.IGNORECASE,
    ):
        return True
    # Some prop labels are only a player name followed by the score, e.g.
    # "Lorenzo Musetti 2-0". A normal moneyline title contains both players.
    if not re.search(r"\b(?:vs?\.?|at)\b", raw_label, flags=re.IGNORECASE) and re.search(
        r"\b[0-5]\s*[-:]\s*[0-5]\s*$", raw_label.strip()
    ):
        return True

    # Polymarket exact-set-score slugs have appeared with an `-es-0-2` suffix.
    raw_slug = str(market.get("slug") or "").strip().lower()
    if re.search(r"(?:^|[-_])es[-_]\d+[-_]\d+(?:$|[-_])", raw_slug):
        return True
    if any(token in raw_slug for token in ("exact-score", "correct-score", "set-score")):
        return True

    legacy = normalize_market_text(market.get("sportsMarketType"))
    if legacy and any(
        term in legacy
        for term in ("prop", "spread", "total", "exact score", "set score", "game winner")
    ):
        return True
    return False


def is_match_winner_moneyline(market: Mapping[str, Any]) -> bool:
    """Return True only for the ordinary two-player match-winner moneyline."""
    if has_non_moneyline_signature(market):
        return False

    v2 = str(market.get("sportsMarketTypeV2") or "").strip().upper()
    if v2:
        if v2 in {MONEYLINE_V2, "MONEYLINE"}:
            return True
        if v2 in UNSPECIFIED_V2 and has_binary_named_competitor_sides(market):
            return True
        return False

    legacy = normalize_market_text(market.get("sportsMarketType"))
    if legacy:
        if legacy in {
            "moneyline",
            "money line",
            "match winner",
            "tennis match winner",
            "tennis moneyline",
            "winner",
        }:
            return True
        if "match winner" in legacy or "moneyline" in legacy or "money line" in legacy:
            return True
        # An explicit but unrecognized sports type is not safe enough to trade.
        return False

    # Current sports payloads sometimes omit both market-type fields and use a
    # generic title. Two named competitors on opposite LONG/SHORT contracts are
    # sufficient positive evidence after the non-moneyline checks above pass.
    if has_binary_named_competitor_sides(market):
        return True

    # Conservative text fallback for older payloads that omit sports type fields.
    text = market_validation_text(market)
    return any(
        phrase in text
        for phrase in (
            "match winner",
            "to win the match",
            "to win match",
            "will win the match",
            "moneyline",
            "money line",
        )
    )
