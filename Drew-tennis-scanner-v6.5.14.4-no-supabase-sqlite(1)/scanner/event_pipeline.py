from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional


def normalize_label(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[_/\-]+", " ", text)
    return " ".join(text.split())


def event_type_text(event: Mapping[str, Any]) -> str:
    return normalize_label(
        " ".join(
            [
                str(event.get("event_type_type") or ""),
                str(event.get("tournament_name") or ""),
                str(event.get("tournament_round") or ""),
            ]
        )
    )


def _has_doubles_players(event: Mapping[str, Any]) -> bool:
    names = [str(event.get("event_first_player") or ""), str(event.get("event_second_player") or "")]
    return any("/" in name for name in names)


def is_singles_event(event: Mapping[str, Any]) -> bool:
    text = event_type_text(event)
    if any(token in text for token in ("doubles", "mixed doubles")) or _has_doubles_players(event):
        return False
    if "singles" in text:
        return True
    # Some low-level feeds label the tournament but omit the word Singles.
    if re.search(r"\bitf\s+[mw]\s*\d+\b", text) or re.search(r"\b[wm]\s*\d+\b", text):
        return True
    return False




def event_is_qualification(event: Mapping[str, Any]) -> bool:
    """Return True when API Tennis marks or labels the event as qualifying.

    API Tennis supplies ``event_qualification`` on many fixtures, but some live
    rows communicate the same state only in the tournament/round text.  Keep
    both paths so a missing flag cannot silently turn a qualifier into a main-
    draw match.
    """

    raw_flag = event.get("event_qualification")
    if isinstance(raw_flag, bool):
        if raw_flag:
            return True
    elif raw_flag not in (None, ""):
        normalized_flag = normalize_label(raw_flag)
        if normalized_flag in {"1", "true", "yes", "y"}:
            return True

    text = normalize_label(
        " ".join(
            [
                str(event.get("tournament_name") or ""),
                str(event.get("tournament_round") or ""),
            ]
        )
    )
    return bool(
        re.search(r"\bqualif(?:ication|ications|ying|ier|iers|y)?\b", text)
    )

def event_league(event: Mapping[str, Any]) -> str:
    text = event_type_text(event)
    if any(token in text for token in ("women", "wta", " w15", " w25", " w35", " w50", " w75", " w100")):
        return "WTA"
    if any(token in text for token in ("men", "atp", " m15", " m25")):
        return "ATP"
    return "Unknown"


def event_competition_group(event: Mapping[str, Any]) -> str:
    text = event_type_text(event)
    if "itf" in text or re.search(r"\b[wm]\s*(15|25|35|50|75|100)\b", text):
        return "ITF"
    if "challenger" in text:
        return "Challenger"
    if "atp" in text or "wta" in text:
        return "Tour"
    return "Other"


def is_itf_m15_mens_singles(event: Mapping[str, Any]) -> bool:
    text = event_type_text(event)
    return is_singles_event(event) and event_league(event) == "ATP" and (
        "itf men singles" in text or bool(re.search(r"\bitf\s*m\s*15\b", text)) or bool(re.search(r"\bm\s*15\b", text))
    )


def event_key(event: Mapping[str, Any], index: int = 0) -> str:
    return str(event.get("event_key") or event.get("match_key") or f"unknown-{index}")


@dataclass
class PipelineRow:
    event_key: str
    player1: str
    player2: str
    tournament: str
    event_type: str
    league: str
    competition_group: str
    included: bool
    reason: str
    source: str
    has_score: bool
    has_server: bool
    has_pointbypoint: bool
    has_statistics: bool
    raw_event: Dict[str, Any] = field(repr=False)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "Event key": self.event_key,
            "Match": f"{self.player1} vs {self.player2}",
            "Tournament": self.tournament,
            "Event type": self.event_type,
            "League": self.league,
            "Group": self.competition_group,
            "Included": self.included,
            "Reason": self.reason,
            "Source": self.source,
            "Score": self.has_score,
            "Server": self.has_server,
            "Point-by-point": self.has_pointbypoint,
            "Statistics": self.has_statistics,
        }


@dataclass
class PipelineResult:
    all_events: List[Dict[str, Any]]
    supported_events: List[Dict[str, Any]]
    rows: List[PipelineRow]
    counts: Dict[str, int]

    @property
    def excluded_events(self) -> List[Dict[str, Any]]:
        return [row.raw_event for row in self.rows if not row.included]


def classify_event(event: Dict[str, Any], enabled_groups: Optional[Iterable[str]] = None) -> PipelineRow:
    p1 = str(event.get("event_first_player") or "").strip()
    p2 = str(event.get("event_second_player") or "").strip()
    group = event_competition_group(event)
    league = event_league(event)
    event_type = str(event.get("event_type_type") or "Unknown")
    allowed = set(enabled_groups or ("Tour", "Challenger"))

    included = True
    reason = "Supported ATP Tour/Challenger singles"
    if not p1 or not p2:
        included, reason = False, "Missing player name"
    elif not is_singles_event(event):
        included, reason = False, "Not a supported singles match"
    elif league != "ATP":
        included, reason = False, "Version 6.0 is ATP-only"
    elif group not in allowed:
        included, reason = False, f"{group} disabled or unsupported"
    elif group not in {"Tour", "Challenger"}:
        included, reason = False, "Only ATP Tour and Challenger are supported"

    return PipelineRow(
        event_key=event_key(event),
        player1=p1 or "Unknown",
        player2=p2 or "Unknown",
        tournament=str(event.get("tournament_name") or ""),
        event_type=event_type,
        league=league,
        competition_group=group,
        included=included,
        reason=reason,
        source=str(event.get("_api_source") or "get_livescore"),
        has_score=bool(event.get("scores") or event.get("event_final_result")),
        has_server=event.get("event_serve") in {"First Player", "Second Player"},
        has_pointbypoint=bool(event.get("pointbypoint")),
        has_statistics=bool(event.get("statistics")),
        raw_event=event,
    )


def build_pipeline(events: Iterable[Dict[str, Any]], enabled_groups: Optional[Iterable[str]] = None) -> PipelineResult:
    all_events = [event for event in events if isinstance(event, dict)]
    rows = [classify_event(event, enabled_groups) for event in all_events]
    supported = [row.raw_event for row in rows if row.included]
    reason_counts = Counter(row.reason for row in rows if not row.included)
    counts: Dict[str, int] = {
        "api_events": len(all_events),
        "supported_singles": len(supported),
        "excluded": len(all_events) - len(supported),
        "tour": sum(row.included and row.competition_group == "Tour" for row in rows),
        "challenger": sum(row.included and row.competition_group == "Challenger" for row in rows),
        "itf": sum(row.included and row.competition_group == "ITF" for row in rows),
        "itf_m15_men": sum(row.included and is_itf_m15_mens_singles(row.raw_event) for row in rows),
        "missing_pointbypoint_but_included": sum(row.included and not row.has_pointbypoint for row in rows),
        "missing_statistics_but_included": sum(row.included and not row.has_statistics for row in rows),
    }
    for reason, count in reason_counts.items():
        counts[f"excluded:{reason}"] = count
    return PipelineResult(all_events, supported, rows, counts)
