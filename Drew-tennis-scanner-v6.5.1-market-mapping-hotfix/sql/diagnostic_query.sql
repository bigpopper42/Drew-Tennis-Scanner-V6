select
    scanned_at,
    player,
    opponent,
    tournament,
    decision_status,
    decision_reason,
    stability_score,
    match_closing_set,
    tiebreak,
    break_lead,
    serving,
    backed_player_games_in_set,
    opponent_games_in_set,
    current_game_score,
    current_set_breaks_suffered,
    effective_service_points_won_pct,
    data_completeness_pct,
    core_completeness_pct,
    scoring_completeness_pct,
    warnings,
    errors
from public.shadow_scans
order by scanned_at desc
limit 100;
