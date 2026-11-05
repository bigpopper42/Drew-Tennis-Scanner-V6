from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class MatchInput:
    """One backed-player view of a live match.

    Version 6.0 keeps Polymarket data on the object for display and recording,
    but no price field participates in qualification or position sizing.
    """

    player: str
    opponent: str
    tournament: str
    surface: str = "Unknown"

    # Informational only in Version 6.0.
    market_price_cents: float = 0.0
    market_price_timestamp: Optional[str] = None
    market_volume: Optional[float] = None
    market_liquidity: Optional[float] = None

    bankroll: float = 0.0
    league: str = "Unknown"
    competition_group: str = "Unknown"
    is_qualification: bool = False
    best_of_sets: int = 3
    current_set_number: Optional[int] = None

    match_closing_set: Optional[bool] = None
    straight_set_closing: bool = False
    deciding_set: bool = False
    break_lead: Optional[int] = None
    serving: Optional[bool] = None
    serving_for_match: bool = False
    tiebreak: Optional[bool] = None
    backed_player_games_in_set: Optional[int] = None
    opponent_games_in_set: Optional[int] = None
    current_game_score: str = "0-0"
    completed_sets: Optional[int] = None
    last_completed_game_was_break_by_backed: Optional[bool] = None
    current_service_game_reached_30_0: Optional[bool] = None
    current_service_game_reached_40_0: Optional[bool] = None

    # Set-level and match-level stability inputs.
    breaks_suffered_by_set: List[int] = field(default_factory=list)
    breaks_suffered_total: Optional[int] = None
    current_set_breaks_suffered: Optional[int] = None
    service_points_won_pct: Optional[float] = None
    current_set_service_points_won_pct: Optional[float] = None
    effective_service_points_won_pct: Optional[float] = None
    opponent_service_points_won_pct: Optional[float] = None
    opponent_current_set_service_points_won_pct: Optional[float] = None
    first_serve_points_won_pct: Optional[float] = None
    current_set_first_serve_points_won_pct: Optional[float] = None
    first_serve_in_pct: Optional[float] = None
    current_set_first_serve_in_pct: Optional[float] = None
    break_points_created: Optional[int] = None
    break_points_faced: Optional[int] = None
    comfortable_holds_pct: Optional[float] = None  # retained for compatibility; not scored
    double_faults_per_service_game: Optional[float] = None

    recent_form_label: str = "Unknown"  # deliberately ignored by Version 6.0
    ranking: Optional[int] = None
    opponent_ranking: Optional[int] = None
    surface_form_label: str = "Unknown"  # deliberately ignored by Version 6.0

    notes: str = ""
    data_completeness_pct: float = 0.0
    core_completeness_pct: float = 0.0
    event_key: Optional[str] = None
    api_source: str = "manual"
    mapping_warnings: List[str] = field(default_factory=list)
    field_provenance: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
