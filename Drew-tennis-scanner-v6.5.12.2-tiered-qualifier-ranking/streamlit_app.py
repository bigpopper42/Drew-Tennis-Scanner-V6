from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional

import pandas as pd
import streamlit as st

from scanner.api_tennis import get_live_snapshot, get_rankings, summarize_live_event
from scanner.database import delete_recommendation, init_db, load_recommendations, save_recommendation, update_result
from scanner.decision import Decision, evaluate_match
from scanner.event_pipeline import build_pipeline, event_competition_group, event_key, event_league
from scanner.live_mapping import build_live_scanner_mapping
from scanner.live_scan import PlayerScanResult, scan_both_players
from scanner.models import MatchInput
from scanner.supabase_dashboard import SupabaseDashboardClient
from scanner.polymarket import (
    extract_bbo_prices,
    extract_display_price,
    get_bbo,
    infer_player_prices,
    match_tennis_market,
    search_us_markets,
)

VERSION = "6.1"
st.set_page_config(page_title=f"Tennis Scanner V{VERSION}", page_icon="🎾", layout="wide")
init_db()


def state_default(key: str, value: Any) -> None:
    if key not in st.session_state:
        st.session_state[key] = value


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return default if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return default if value in (None, "") else int(float(value))
    except (TypeError, ValueError):
        return default


def optional_float(value: Any) -> Optional[float]:
    number = safe_float(value)
    return number if number > 0 else None


def optional_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    return safe_int(value)


def parse_breaks(value: Any) -> List[int]:
    output: List[int] = []
    for token in str(value or "").split(","):
        try:
            output.append(max(0, int(token.strip())))
        except ValueError:
            continue
    return output


def safe_event_key(event: Mapping[str, Any], index: int = 0) -> str:
    raw = event_key(event, index)
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", raw)


def get_secret(name: str, default: str = "") -> str:
    try:
        return str(st.secrets.get(name, default))
    except Exception:
        return default


def parse_utc_datetime(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    try:
        parsed = pd.to_datetime(value, utc=True, errors="coerce")
    except Exception:
        return None
    if pd.isna(parsed):
        return None
    return parsed.to_pydatetime()


def seconds_since(value: Any) -> Optional[float]:
    parsed = parse_utc_datetime(value)
    if parsed is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())


def age_label(value: Any) -> str:
    seconds = seconds_since(value)
    if seconds is None:
        return "Unknown"
    if seconds < 60:
        return f"{int(seconds)} sec ago"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} hr ago"
    return f"{int(seconds // 86400)} days ago"


def compact_json_messages(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if str(item).strip()]
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return []
        try:
            decoded = json.loads(text)
        except Exception:
            return [text]
        return compact_json_messages(decoded)
    return [str(value)]


@st.cache_data(ttl=15, show_spinner=False)
def load_supabase_dashboard(
    supabase_url: str,
    supabase_key: str,
    cycle_limit: int = 120,
    scan_limit: int = 500,
) -> Dict[str, Any]:
    client = SupabaseDashboardClient(supabase_url, supabase_key)
    data = client.fetch_dashboard_data(
        worker_limit=10,
        cycle_limit=cycle_limit,
        scan_limit=scan_limit,
    )
    return {
        "workers": data.workers,
        "cycles": data.cycles,
        "scans": data.scans,
        "loaded_at": datetime.now(timezone.utc).isoformat(),
    }


@st.cache_data(ttl=3600, show_spinner=False)
def cached_rankings(api_key: str, league: str) -> Dict[str, int]:
    return get_rankings(api_key, league)


def get_selected_rankings(api_key: str, event: Mapping[str, Any]) -> Dict[str, Dict[str, int]]:
    league = event_league(event)
    if league not in {"ATP", "WTA"} or not api_key:
        return {}
    try:
        return {league: cached_rankings(api_key, league)}
    except Exception as exc:
        st.warning(f"{league} rankings are unavailable. The match still scans: {exc}")
        return {league: {}}


def build_manual_match() -> MatchInput:
    ranking = safe_int(st.session_state.get("scan_ranking"))
    return MatchInput(
        player=str(st.session_state.get("scan_player") or "Unknown player"),
        opponent=str(st.session_state.get("scan_opponent") or "Unknown opponent"),
        tournament=str(st.session_state.get("scan_tournament") or "Unknown tournament"),
        surface="Unknown",
        market_price_cents=max(0.0, safe_float(st.session_state.get("scan_market_price"))),
        bankroll=max(0.0, safe_float(st.session_state.get("scan_bankroll"))),
        match_closing_set=bool(st.session_state.get("scan_match_closing_set")),
        break_lead=optional_int(st.session_state.get("scan_break_lead")),
        serving=bool(st.session_state.get("scan_serving")),
        tiebreak=bool(st.session_state.get("scan_tiebreak")),
        backed_player_games_in_set=optional_int(st.session_state.get("scan_games_in_set")),
        current_game_score=str(st.session_state.get("scan_game_score") or "0-0"),
        completed_sets=optional_int(st.session_state.get("scan_completed_sets")),
        breaks_suffered_by_set=parse_breaks(st.session_state.get("scan_breaks_by_set")),
        service_points_won_pct=optional_float(st.session_state.get("scan_service_points")),
        first_serve_points_won_pct=optional_float(st.session_state.get("scan_first_serve_points")),
        first_serve_in_pct=optional_float(st.session_state.get("scan_first_serve_in")),
        breaks_suffered_total=optional_int(st.session_state.get("scan_breaks_total")),
        break_points_faced=optional_int(st.session_state.get("scan_break_points_faced")),
        comfortable_holds_pct=optional_float(st.session_state.get("scan_comfortable_holds")),
        double_faults_per_service_game=(safe_float(st.session_state.get("scan_df_rate")) if st.session_state.get("scan_df_known") else None),
        recent_form_label="Unknown",
        ranking=ranking or None,
        surface_form_label="Unknown",
        notes=str(st.session_state.get("scan_notes") or ""),
        data_completeness_pct=100.0,
        core_completeness_pct=100.0,
        api_source="manual",
    )


def record_for(
    match: MatchInput,
    decision: Decision,
    *,
    source: str,
    event_type: str,
    league: str,
    competition_group: str,
    market: Optional[Dict[str, Any]] = None,
    market_side: Optional[str] = None,
) -> Dict[str, Any]:
    market = market or {}
    return {
        "player": match.player,
        "opponent": match.opponent,
        "tournament": match.tournament,
        "event_type": event_type,
        "league": league,
        "competition_group": competition_group,
        "event_key": match.event_key,
        "api_source": match.api_source,
        "market_price_cents": match.market_price_cents,
        "status": decision.status,
        "stability_score": decision.score,
        "required_score": decision.minimum_score,
        "data_completeness_pct": decision.data_completeness_pct,
        "core_completeness_pct": decision.core_completeness_pct,
        "scoring_completeness_pct": decision.scoring_completeness_pct,
        "stake_pct": decision.stake_pct,
        "stake_amount": decision.stake_amount,
        "bankroll": match.bankroll,
        "notes": match.notes,
        "source": source,
        "market_title": market.get("market_title") or market.get("event_title"),
        "market_slug": market.get("market_slug"),
        "market_side": market_side,
    }


def status_box(status: str) -> None:
    if status == "TRADE":
        st.success(status)
    elif status in {"WAIT", "PRICE NEEDED", "DATA REVIEW"}:
        st.warning(status)
    else:
        st.error(status)


def show_decision(
    match: MatchInput,
    decision: Decision,
    *,
    key: str,
    record_kwargs: Optional[Dict[str, Any]] = None,
) -> None:
    status_box(decision.status)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Stability", f"{decision.score:.1f}/100")
    c2.metric("Required", f"{decision.minimum_score:.1f}" if decision.minimum_score else "Price needed")
    c3.metric("Data", f"{decision.data_completeness_pct:.0f}%" if decision.data_completeness_pct else "Manual")
    c4.metric("Stake", f"${decision.stake_amount:.2f} ({decision.stake_pct * 100:.0f}%)")
    st.write(decision.reason)

    with st.expander("Rules, risks, and score breakdown", expanded=decision.status in {"TRADE", "DATA REVIEW"}):
        left, right = st.columns(2)
        with left:
            st.markdown("**Passed**")
            for item in decision.passed:
                st.write("✅", item)
        with right:
            st.markdown("**Risks / blockers**")
            if not decision.concerns:
                st.write("No major concerns")
            for item in decision.concerns:
                st.write("⚠️", item)

        score_rows = []
        for factor, points in decision.score_parts.items():
            score_rows.append({
                "Factor": factor,
                "Points": points,
                "Data available": "Yes" if decision.factor_availability.get(factor) else "No",
            })
        st.caption("Recent form and surface form are removed. Missing optional factors never crash the scan; they contribute zero points and lower data completeness.")
        st.dataframe(pd.DataFrame(score_rows), use_container_width=True, hide_index=True)

    if st.button("Save to paper log", key=f"save_{key}", use_container_width=True):
        kwargs = record_kwargs or {
            "source": "manual",
            "event_type": "Manual",
            "league": "Unknown",
            "competition_group": "Manual",
        }
        row_id = save_recommendation(record_for(match, decision, **kwargs))
        st.success(f"Saved as row {row_id}.")


def mapping_table(result: PlayerScanResult) -> pd.DataFrame:
    rows = []
    for name, status in result.mapping.field_status.items():
        rows.append({
            "Field": name,
            "Value": status.value,
            "Available": status.available,
            "Source": status.source,
            "Note": status.note,
        })
    return pd.DataFrame(rows)


def market_result_for_event(event_id: str) -> Dict[str, Any]:
    return st.session_state.get(f"market_result_{event_id}", {"candidates": [], "inferred": {}, "error": None})


def find_market_and_prices(event: Dict[str, Any], event_id: str) -> Dict[str, Any]:
    summary = summarize_live_event(event)
    try:
        candidates = match_tennis_market(
            summary["player1"],
            summary["player2"],
            league=event_league(event),
            competition_group=event_competition_group(event),
            tournament=summary["tournament"],
            event_start=f"{event.get('event_date') or ''}T{event.get('event_time') or ''}",
        )
        selected = candidates[0] if candidates else None
        inferred: Dict[str, Any] = {"prices": {}, "sides": {}, "complete": False}
        if selected and selected.get("market_slug"):
            bbo = get_bbo(selected.get("market_slug"))
            prices = extract_bbo_prices(bbo)
            inferred = infer_player_prices(
                selected,
                summary["player1"],
                summary["player2"],
                prices,
                extract_display_price(selected),
            )
            inferred["bbo"] = bbo
            inferred["market"] = selected
        result = {"candidates": candidates, "selected": selected, "inferred": inferred, "error": None}
    except Exception as exc:
        result = {"candidates": [], "selected": None, "inferred": {}, "error": str(exc)}
    st.session_state[f"market_result_{event_id}"] = result
    return result


def run_live_scan(event: Dict[str, Any], event_id: str, api_key: str, bankroll: float, prices: Mapping[str, Any]) -> None:
    rankings = get_selected_rankings(api_key, event)
    results = scan_both_players(event, rankings, price_by_player=prices, bankroll=bankroll)
    st.session_state[f"scan_results_{event_id}"] = results


for key, value in {
    "scan_player": "Example Player",
    "scan_opponent": "Example Opponent",
    "scan_tournament": "Tennis Event",
    "scan_ranking": 0,
    "scan_bankroll": 100.0,
    "scan_market_price": 98.0,
    "scan_match_closing_set": True,
    "scan_break_lead": 1,
    "scan_serving": True,
    "scan_tiebreak": False,
    "scan_games_in_set": 5,
    "scan_game_score": "0-0",
    "scan_completed_sets": 1,
    "scan_breaks_by_set": "1",
    "scan_service_points": 67.0,
    "scan_first_serve_points": 75.0,
    "scan_first_serve_in": 63.0,
    "scan_breaks_total": 1,
    "scan_break_points_faced": 3,
    "scan_comfortable_holds": 65.0,
    "scan_df_rate": 0.10,
    "scan_df_known": True,
    "scan_notes": "",
    "live_scan_bankroll": 100.0,
    "live_timezone": "America/Phoenix",
    "live_groups": ["Tour", "Challenger", "ITF"],
    "include_fixtures_fallback": True,
}.items():
    state_default(key, value)

st.title("🎾 Tennis Scanner Assistant")
st.caption(
    "Version 6.5.12.2: live tennis scanning, Discord alerts, Railway/Supabase monitoring, and guarded Polymarket US execution with authenticated live-market side and order-book validation."
)

page = st.selectbox(
    "Workspace",
    ["Worker dashboard", "Live scanner", "Detailed scan", "Diagnostics", "Paper log", "Polymarket search"],
    key="workspace_page",
)

if page == "Worker dashboard":
    st.subheader("Railway worker dashboard")
    st.caption(
        "This page reads the worker heartbeat, completed cycles, and shadow scans from Supabase. It does not control Railway and cannot place trades."
    )

    supabase_url = get_secret("SUPABASE_URL", "")
    supabase_key = (
        get_secret("SUPABASE_SECRET_KEY", "")
        or get_secret("SUPABASE_SERVICE_ROLE_KEY", "")
    )
    offline_after_seconds = max(60, safe_int(get_secret("WORKER_OFFLINE_AFTER_SECONDS", "120"), 120))

    if not supabase_url or not supabase_key:
        st.error("The dashboard cannot connect until Supabase is added to Streamlit Secrets.")
        st.code(
            'SUPABASE_URL = "https://YOUR_PROJECT_REF.supabase.co"\n'
            'SUPABASE_SECRET_KEY = "YOUR_SERVER_SIDE_SECRET_KEY"\n'
            'WORKER_OFFLINE_AFTER_SECONDS = 120',
            language="toml",
        )
        st.warning(
            "Keep the secret only in Streamlit Secrets. Do not paste it into GitHub, the app interface, screenshots, or browser code."
        )
    else:
        controls_left, controls_right = st.columns([3, 1])
        with controls_left:
            st.write("Worker data refreshes from Supabase and is cached for 15 seconds.")
        with controls_right:
            if st.button("Refresh dashboard", type="primary", use_container_width=True):
                load_supabase_dashboard.clear()
                st.rerun()

        try:
            with st.spinner("Loading Railway worker data from Supabase..."):
                dashboard = load_supabase_dashboard(supabase_url, supabase_key)
        except Exception as exc:
            st.error(f"Could not load the Supabase dashboard: {exc}")
            dashboard = {"workers": [], "cycles": [], "scans": [], "loaded_at": None}

        workers = dashboard.get("workers") or []
        cycles = dashboard.get("cycles") or []
        scans = dashboard.get("scans") or []
        worker = workers[0] if workers else {}
        latest_cycle = cycles[0] if cycles else {}

        heartbeat_age = seconds_since(worker.get("last_seen_at"))
        heartbeat_fresh = heartbeat_age is not None and heartbeat_age <= offline_after_seconds
        worker_status = str(worker.get("status") or "UNKNOWN").upper()
        worker_online = bool(worker) and heartbeat_fresh and worker_status not in {"STOPPED", "FAILED"}
        worker_degraded = worker_online and worker_status == "DEGRADED"

        if not worker:
            st.error("No worker heartbeat exists in Supabase yet.")
        elif worker_degraded:
            st.warning(f"Worker is online but degraded. Last heartbeat: {age_label(worker.get('last_seen_at'))}.")
        elif worker_online:
            st.success(f"Worker is online. Last heartbeat: {age_label(worker.get('last_seen_at'))}.")
        else:
            st.error(
                f"Worker appears offline or stale. Last heartbeat: {age_label(worker.get('last_seen_at'))}. "
                f"Offline threshold: {offline_after_seconds} seconds."
            )

        health1, health2, health3, health4 = st.columns(4)
        health1.metric("Worker", "ONLINE" if worker_online else "OFFLINE")
        health2.metric("Worker status", worker_status)
        health3.metric("Last heartbeat", age_label(worker.get("last_seen_at")))
        health4.metric(
            "Last cycle",
            str(latest_cycle.get("status") or "No cycle"),
            delta=age_label(latest_cycle.get("completed_at") or latest_cycle.get("started_at")),
            delta_color="off",
        )

        metric_source = latest_cycle or (worker.get("metrics") if isinstance(worker.get("metrics"), dict) else {})
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("API live events", safe_int(metric_source.get("api_events")))
        m2.metric("Supported matches", safe_int(metric_source.get("supported_events")))
        m3.metric("Markets matched", safe_int(metric_source.get("markets_matched")))
        m4.metric("Markets unmatched", safe_int(metric_source.get("markets_unmatched")))
        m5, m6, m7, m8 = st.columns(4)
        m5.metric("Player scans", safe_int(metric_source.get("player_scans")))
        m6.metric("Trade signals", safe_int(metric_source.get("trade_signals")))
        m7.metric("Inserted scans", safe_int(metric_source.get("inserted_scans")))
        m8.metric("Duplicate states", safe_int(metric_source.get("duplicate_scans")))

        st.caption(
            f"Dashboard loaded {age_label(dashboard.get('loaded_at'))}. "
            f"Worker version: {worker.get('version') or 'Unknown'} | Worker ID: {worker.get('worker_id') or 'Unknown'}"
        )

        overview_tab, candidates_tab, scans_tab, problems_tab = st.tabs(
            ["Cycle history", "Trade candidates", "Latest match states", "Warnings and errors"]
        )

        with overview_tab:
            if not cycles:
                st.info("No scan cycles are stored yet.")
            else:
                cycle_df = pd.DataFrame(cycles)
                display_columns = [
                    "started_at", "status", "duration_seconds", "api_events",
                    "supported_events", "markets_matched", "markets_unmatched",
                    "player_scans", "trade_signals", "inserted_scans", "duplicate_scans",
                ]
                for column in display_columns:
                    if column not in cycle_df.columns:
                        cycle_df[column] = None
                cycle_display = cycle_df[display_columns].copy()
                cycle_display["started_at"] = pd.to_datetime(
                    cycle_display["started_at"], utc=True, errors="coerce"
                )
                st.dataframe(
                    cycle_display,
                    use_container_width=True,
                    hide_index=True,
                    height=360,
                )
                chart_df = cycle_display.dropna(subset=["started_at"]).sort_values("started_at")
                if not chart_df.empty:
                    chart_df = chart_df.set_index("started_at")
                    st.markdown("#### Recent cycle activity")
                    st.line_chart(
                        chart_df[["supported_events", "markets_matched", "player_scans", "trade_signals"]],
                        height=260,
                    )

        with candidates_tab:
            trade_rows = [row for row in scans if str(row.get("decision_status") or "").upper() == "TRADE"]
            if not trade_rows:
                st.info("No TRADE signals are stored in the loaded scan window.")
            else:
                trade_df = pd.DataFrame(trade_rows)
                candidate_columns = [
                    "scanned_at", "player", "opponent", "tournament",
                    "market_found", "market_price_cents", "stability_score",
                    "required_score", "break_lead", "serving",
                    "data_completeness_pct", "decision_reason",
                ]
                for column in candidate_columns:
                    if column not in trade_df.columns:
                        trade_df[column] = None
                st.dataframe(
                    trade_df[candidate_columns],
                    use_container_width=True,
                    hide_index=True,
                    height=430,
                )
                st.download_button(
                    "Download trade candidates CSV",
                    trade_df.to_csv(index=False).encode("utf-8"),
                    "tennis_scanner_v6.1_trade_candidates.csv",
                    "text/csv",
                )

        with scans_tab:
            if not scans:
                st.info("No shadow scans are stored yet. This is expected until supported live matches are processed.")
            else:
                scan_df = pd.DataFrame(scans)
                if {"event_key", "player", "scanned_at"}.issubset(scan_df.columns):
                    scan_df["scanned_at_sort"] = pd.to_datetime(
                        scan_df["scanned_at"], utc=True, errors="coerce"
                    )
                    scan_df = (
                        scan_df.sort_values("scanned_at_sort", ascending=False)
                        .drop_duplicates(subset=["event_key", "player"], keep="first")
                    )
                state_columns = [
                    "scanned_at", "player", "opponent", "tournament",
                    "decision_status", "decision_reason", "stability_score",
                    "match_closing_set", "tiebreak", "break_lead", "serving",
                    "backed_player_games_in_set", "opponent_games_in_set",
                    "current_game_score", "current_set_breaks_suffered",
                    "effective_service_points_won_pct", "market_found",
                    "market_price_cents", "event_final_result", "event_game_result",
                    "event_serve", "data_completeness_pct",
                    "core_completeness_pct", "scoring_completeness_pct",
                    "warnings", "errors",
                ]
                for column in state_columns:
                    if column not in scan_df.columns:
                        scan_df[column] = None
                decision_options = ["ALL"] + sorted(
                    {str(value) for value in scan_df["decision_status"].dropna().tolist()}
                )
                decision_filter = st.selectbox(
                    "Decision filter", decision_options, key="dashboard_decision_filter"
                )
                filtered_df = scan_df
                if decision_filter != "ALL":
                    filtered_df = scan_df[scan_df["decision_status"] == decision_filter]
                st.dataframe(
                    filtered_df[state_columns],
                    use_container_width=True,
                    hide_index=True,
                    height=470,
                )

        with problems_tab:
            messages: List[Dict[str, str]] = []
            if worker.get("last_error"):
                messages.append({
                    "Time": str(worker.get("last_seen_at") or ""),
                    "Source": "Worker heartbeat",
                    "Level": "ERROR",
                    "Message": str(worker.get("last_error")),
                })
            for cycle in cycles[:50]:
                for message in compact_json_messages(cycle.get("errors")):
                    messages.append({
                        "Time": str(cycle.get("completed_at") or cycle.get("started_at") or ""),
                        "Source": "Scan cycle",
                        "Level": "ERROR",
                        "Message": message,
                    })
                for message in compact_json_messages(cycle.get("warnings")):
                    messages.append({
                        "Time": str(cycle.get("completed_at") or cycle.get("started_at") or ""),
                        "Source": "Scan cycle",
                        "Level": "WARNING",
                        "Message": message,
                    })
            for scan in scans[:100]:
                for message in compact_json_messages(scan.get("errors")):
                    messages.append({
                        "Time": str(scan.get("scanned_at") or ""),
                        "Source": f"{scan.get('player')} vs {scan.get('opponent')}",
                        "Level": "ERROR",
                        "Message": message,
                    })
            if not messages:
                st.success("No worker, cycle, or recent scan errors are stored in the loaded window.")
            else:
                st.dataframe(
                    pd.DataFrame(messages),
                    use_container_width=True,
                    hide_index=True,
                    height=470,
                )


if page == "Live scanner":
    st.subheader("Live opportunity scanner")
    st.info(
        "API Tennis is the source of truth. Every raw live event is counted first, then supported singles are classified. Nothing is silently discarded."
    )

    settings_col, action_col = st.columns([2, 1])
    with settings_col:
        st.multiselect("Competition groups", ["Tour", "Challenger", "ITF"], key="live_groups")
        st.text_input("API Tennis timezone", key="live_timezone")
        st.checkbox("Merge same-day fixtures that API Tennis marks live", key="include_fixtures_fallback")
        api_key = st.text_input(
            "API Tennis key",
            value=get_secret("API_TENNIS_KEY", ""),
            type="password",
            key="live_api_key",
        )
    with action_col:
        st.write("")
        st.write("")
        fetch_clicked = st.button("Refresh live matches", type="primary", use_container_width=True)
        clear_clicked = st.button("Clear live session", use_container_width=True)

    if clear_clicked:
        for key in list(st.session_state):
            if key.startswith(("live_", "market_result_", "scan_results_", "price_")) and key not in {
                "live_api_key", "live_timezone", "live_groups", "live_scan_bankroll"
            }:
                st.session_state.pop(key, None)
        st.rerun()

    if fetch_clicked:
        try:
            with st.spinner("Loading the complete API Tennis live snapshot..."):
                snapshot = get_live_snapshot(
                    api_key,
                    timezone=st.session_state.get("live_timezone") or "America/Phoenix",
                    include_live_fixtures_fallback=bool(st.session_state.get("include_fixtures_fallback")),
                )
                pipeline = build_pipeline(snapshot.events, st.session_state.get("live_groups"))
                st.session_state["live_events_all"] = snapshot.events
                st.session_state["live_events_supported"] = pipeline.supported_events
                st.session_state["live_pipeline_rows"] = [row.to_dict() for row in pipeline.rows]
                st.session_state["live_pipeline_counts"] = pipeline.counts
                st.session_state["live_snapshot_summary"] = snapshot.summary()
                st.session_state["live_refreshed_at"] = datetime.now(timezone.utc).isoformat()
            st.success(f"Loaded {len(snapshot.events)} unique live API events; {len(pipeline.supported_events)} supported singles are ready to scan.")
        except Exception as exc:
            st.error(f"Could not fetch API Tennis live data: {exc}")

    counts = st.session_state.get("live_pipeline_counts", {})
    snap = st.session_state.get("live_snapshot_summary", {})
    if counts:
        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("API live events", counts.get("api_events", 0))
        m2.metric("Supported singles", counts.get("supported_singles", 0))
        m3.metric("ITF", counts.get("itf", 0))
        m4.metric("ITF M15 men", counts.get("itf_m15_men", 0))
        m5.metric("Excluded", counts.get("excluded", 0))
        m6.metric("Load time", f"{snap.get('duration_seconds', 0):.1f}s")
        st.caption(
            f"Primary livescore rows: {snap.get('livescore_count', 0)} | Live fixture fallback rows: {snap.get('fixtures_live_count', 0)} | Duplicates merged: {snap.get('duplicates_removed', 0)}"
        )
        for warning in snap.get("warnings", []):
            st.warning(warning)

    all_rows = st.session_state.get("live_pipeline_rows", [])
    if all_rows:
        with st.expander("API ingestion report: every returned event and its inclusion reason"):
            st.dataframe(pd.DataFrame(all_rows), use_container_width=True, hide_index=True, height=320)

    events: List[Dict[str, Any]] = st.session_state.get("live_events_supported", [])
    if events:
        summaries = [summarize_live_event(event) for event in events]
        table = pd.DataFrame([
            {
                "Match": f"{row['player1']} vs {row['player2']}",
                "Tournament": row["tournament"],
                "Type": row["event_type"],
                "Status": row["status"],
                "Sets": row["score"],
                "Game": row["game_score"],
                "Serving": row["serving"],
                "Stats": row["statistics_count"],
                "PBP games": row["pointbypoint_count"],
                "Source": row["source"],
            }
            for row in summaries
        ])
        st.dataframe(table, use_container_width=True, hide_index=True, height=min(460, 70 + 35 * len(table)))

        options = [safe_event_key(event, index) for index, event in enumerate(events)]
        labels = {
            options[index]: f"{summaries[index]['player1']} vs {summaries[index]['player2']} — {summaries[index]['tournament']} ({summaries[index]['status']})"
            for index in range(len(events))
        }
        chosen_key = st.selectbox("Select a live match", options=options, format_func=lambda key: labels[key], key="selected_live_event_key")
        selected_index = options.index(chosen_key)
        event = events[selected_index]
        summary = summaries[selected_index]
        event_id = chosen_key
        p1, p2 = summary["player1"], summary["player2"]

        st.markdown(f"## {p1} vs {p2}")
        d1, d2, d3, d4, d5 = st.columns(5)
        d1.metric("Set score", summary["score"])
        d2.metric("Game", summary["game_score"])
        d3.metric("Serving", summary["serving"])
        d4.metric("Group", event_competition_group(event))
        d5.metric("API source", summary["source"])

        market_action, full_action = st.columns(2)
        with market_action:
            if st.button("Find Polymarket market + prices", key=f"find_market_{event_id}", use_container_width=True):
                with st.spinner("Searching this exact API Tennis match on Polymarket..."):
                    market_result = find_market_and_prices(event, event_id)
                if market_result.get("error"):
                    st.error(market_result["error"])
                elif market_result.get("selected"):
                    st.success("Polymarket counterpart found.")
                else:
                    st.warning("No Polymarket counterpart was found. Both player scans can still run with price 0.")
        with full_action:
            if st.button("One-click: find market and scan both players", type="primary", key=f"one_click_{event_id}", use_container_width=True):
                with st.spinner("Finding the market, loading prices, and scanning both players..."):
                    market_result = find_market_and_prices(event, event_id)
                    inferred_prices = (market_result.get("inferred") or {}).get("prices", {})
                    run_live_scan(
                        event,
                        event_id,
                        api_key,
                        safe_float(st.session_state.get("live_scan_bankroll")),
                        inferred_prices,
                    )

        market_result = market_result_for_event(event_id)
        candidates = market_result.get("candidates") or []
        inferred = market_result.get("inferred") or {}
        selected_market = market_result.get("selected") or {}
        if market_result.get("error"):
            st.error(f"Polymarket lookup error: {market_result['error']}")
        if candidates:
            st.write(
                f"**Top market:** {selected_market.get('market_title') or selected_market.get('event_title')}  "
                f"| Match confidence: {selected_market.get('api_match_confidence', 'Unknown')}%  "
                f"| Source: {selected_market.get('lookup_source', 'search')}"
            )
            with st.expander(f"Show {min(10, len(candidates))} market candidates"):
                st.dataframe(pd.DataFrame([
                    {
                        "Event": row.get("event_title"),
                        "Market": row.get("market_title"),
                        "Live": row.get("event_live"),
                        "Confidence": row.get("api_match_confidence"),
                        "Pair similarity": row.get("api_pair_similarity"),
                        "Tournament similarity": row.get("api_tournament_similarity"),
                        "Source": row.get("lookup_source"),
                    }
                    for row in candidates[:10]
                ]), use_container_width=True, hide_index=True)
        elif f"market_result_{event_id}" in st.session_state and not market_result.get("error"):
            st.info("No market counterpart found. This does not stop the live scans.")

        inferred_prices = inferred.get("prices") or {}
        p1_price_key, p2_price_key = f"price_{event_id}_p1", f"price_{event_id}_p2"
        if p1_price_key not in st.session_state:
            st.session_state[p1_price_key] = safe_float(inferred_prices.get(p1))
        if p2_price_key not in st.session_state:
            st.session_state[p2_price_key] = safe_float(inferred_prices.get(p2))
        # When a fresh lookup produces real prices, update only untouched zero fields.
        if inferred_prices.get(p1) and safe_float(st.session_state.get(p1_price_key)) == 0:
            st.session_state[p1_price_key] = safe_float(inferred_prices.get(p1))
        if inferred_prices.get(p2) and safe_float(st.session_state.get(p2_price_key)) == 0:
            st.session_state[p2_price_key] = safe_float(inferred_prices.get(p2))

        price_col1, price_col2, bankroll_col = st.columns(3)
        with price_col1:
            p1_price = st.number_input(f"{p1} price (0 allowed)", 0.0, 99.9, step=0.1, key=p1_price_key)
        with price_col2:
            p2_price = st.number_input(f"{p2} price (0 allowed)", 0.0, 99.9, step=0.1, key=p2_price_key)
        with bankroll_col:
            bankroll = st.number_input("Bankroll (0 allowed)", min_value=0.0, step=1.0, key="live_scan_bankroll")

        if inferred.get("sides"):
            st.caption(f"Market side mapping: {p1} = {inferred['sides'].get(p1) or 'unclear'} | {p2} = {inferred['sides'].get(p2) or 'unclear'}")

        if st.button("Scan both players with shown prices", type="primary", key=f"scan_both_{event_id}", use_container_width=True):
            with st.spinner("Loading selected-tour ranking and scanning both perspectives..."):
                run_live_scan(event, event_id, api_key, bankroll, {p1: p1_price, p2: p2_price})

        results: List[PlayerScanResult] = st.session_state.get(f"scan_results_{event_id}", [])
        if results:
            st.markdown("## Both-player results")
            columns = st.columns(2)
            sides = inferred.get("sides") or {}
            for column, result in zip(columns, results):
                with column:
                    st.markdown(f"### {result.player}")
                    if result.error:
                        st.error(f"Perspective mapping error: {result.error}")
                    c1, c2 = st.columns(2)
                    c1.metric("Mapped data", f"{result.mapping.data_completeness_pct:.0f}%")
                    c2.metric("Core data", f"{result.mapping.core_completeness_pct:.0f}%")
                    kwargs = {
                        "source": "live_api",
                        "event_type": str(event.get("event_type_type") or "Unknown"),
                        "league": event_league(event),
                        "competition_group": event_competition_group(event),
                        "market": selected_market,
                        "market_side": sides.get(result.player),
                    }
                    show_decision(result.match, result.decision, key=f"{event_id}_{result.player}", record_kwargs=kwargs)

                    with st.expander("Field mapping for this player"):
                        st.dataframe(mapping_table(result), use_container_width=True, hide_index=True)
    elif "live_events_supported" in st.session_state:
        st.warning("API Tennis returned events, but none passed the selected singles/group filters. Open Diagnostics to see every exclusion reason.")
    else:
        st.caption("Press Refresh live matches to begin.")

if page == "Detailed scan":
    st.subheader("Detailed manual scan")
    st.caption("Surface and recent form are not part of the Version 6.0 score. Polymarket price is informational only and never changes qualification or sizing.")
    with st.form("manual_scan_form"):
        a, b, c = st.columns(3)
        with a:
            st.text_input("Player being backed", key="scan_player")
            st.text_input("Opponent", key="scan_opponent")
            st.text_input("Tournament", key="scan_tournament")
            st.number_input("Official ATP/WTA ranking (0 if unknown)", min_value=0, key="scan_ranking")
            st.number_input("Bankroll ($, 0 allowed)", min_value=0.0, step=1.0, key="scan_bankroll")
            st.number_input("Polymarket price (cents, 0 allowed)", min_value=0.0, max_value=99.9, step=0.1, key="scan_market_price")
        with b:
            st.checkbox("Winning this set wins the match", key="scan_match_closing_set")
            st.number_input("Break lead", min_value=0, max_value=5, key="scan_break_lead")
            st.checkbox("Backed player is serving", key="scan_serving")
            st.checkbox("Current set is a tiebreak", key="scan_tiebreak")
            st.number_input("Backed player games in current set", min_value=0, max_value=7, key="scan_games_in_set")
            st.selectbox(
                "Current game score (backed player first)",
                ["0-0", "15-0", "30-0", "40-0", "0-15", "15-15", "30-15", "40-15", "0-30", "15-30", "30-30", "40-30", "0-40", "15-40", "30-40", "Deuce", "Ad-In", "Ad-Out"],
                key="scan_game_score",
            )
            st.number_input("Completed sets", min_value=0, max_value=4, key="scan_completed_sets")
            st.text_input("Breaks suffered in completed sets (comma separated)", key="scan_breaks_by_set")
        with c:
            st.number_input("Service points won % (0 unknown)", 0.0, 100.0, step=0.1, key="scan_service_points")
            st.number_input("First-serve points won % (0 unknown)", 0.0, 100.0, step=0.1, key="scan_first_serve_points")
            st.number_input("First serves in % (0 unknown)", 0.0, 100.0, step=0.1, key="scan_first_serve_in")
            st.number_input("Total breaks suffered", 0, 20, key="scan_breaks_total")
            st.number_input("Break points faced", 0, 50, key="scan_break_points_faced")
            st.number_input("Comfortable holds % (0 unknown)", 0.0, 100.0, step=0.1, key="scan_comfortable_holds")
            st.checkbox("Double-fault rate is known", key="scan_df_known")
            st.number_input("Double faults per service game", 0.0, 5.0, step=0.01, key="scan_df_rate")
        st.text_area("Notes", key="scan_notes")
        manual_submit = st.form_submit_button("Analyze match", type="primary", use_container_width=True)

    if manual_submit:
        match = build_manual_match()
        st.session_state["manual_match"] = match
        st.session_state["manual_decision"] = evaluate_match(match)
    if st.session_state.get("manual_match"):
        show_decision(st.session_state["manual_match"], st.session_state["manual_decision"], key="manual")

if page == "Diagnostics":
    st.subheader("Diagnostics and coverage")
    st.caption("This page answers exactly where a missing match or missing field was lost. No event is removed without a recorded reason.")

    counts = st.session_state.get("live_pipeline_counts", {})
    snap = st.session_state.get("live_snapshot_summary", {})
    if counts:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Raw unique events", counts.get("api_events", 0))
        c2.metric("Supported singles", counts.get("supported_singles", 0))
        c3.metric("M15 men", counts.get("itf_m15_men", 0))
        c4.metric("Excluded", counts.get("excluded", 0))
        st.write("**Last refresh:**", st.session_state.get("live_refreshed_at", "Unknown"))
        st.write("**Snapshot:**", snap)
        rows = st.session_state.get("live_pipeline_rows", [])
        if rows:
            st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=430)

        raw_events = st.session_state.get("live_events_all", [])
        st.download_button(
            "Download raw API Tennis snapshot",
            data=json.dumps(raw_events, indent=2, default=str).encode("utf-8"),
            file_name="api_tennis_live_snapshot_v6.1.json",
            mime="application/json",
        )

        supported = st.session_state.get("live_events_supported", [])
        if supported:
            options = [safe_event_key(event, i) for i, event in enumerate(supported)]
            diag_key = st.selectbox(
                "Inspect one event field-by-field",
                options,
                format_func=lambda key: next(
                    (
                        f"{event.get('event_first_player')} vs {event.get('event_second_player')} — {event.get('tournament_name')}"
                        for i, event in enumerate(supported) if safe_event_key(event, i) == key
                    ),
                    key,
                ),
                key="diagnostic_event_key",
            )
            index = options.index(diag_key)
            event = supported[index]
            diag_rankings: Dict[str, Dict[str, int]] = {}
            p1 = str(event.get("event_first_player") or "Unknown")
            p2 = str(event.get("event_second_player") or "Unknown")
            left, right = st.columns(2)
            for column, player in ((left, p1), (right, p2)):
                with column:
                    st.markdown(f"### {player}")
                    mapping = build_live_scanner_mapping(event, player, diag_rankings)
                    st.metric("Data completeness", f"{mapping.data_completeness_pct:.0f}%")
                    st.metric("Core completeness", f"{mapping.core_completeness_pct:.0f}%")
                    st.dataframe(pd.DataFrame([
                        {
                            "Field": name,
                            "Raw/scanner value": status.value,
                            "Available": status.available,
                            "Source": status.source,
                        }
                        for name, status in mapping.field_status.items()
                    ]), use_container_width=True, hide_index=True)
            with st.expander("Raw selected event JSON"):
                st.json(event)
    else:
        st.info("Refresh live matches first. Diagnostics will then show every API event and inclusion reason.")

if page == "Paper log":
    st.subheader("Paper-trading log")
    log_df = load_recommendations()
    if log_df.empty:
        st.info("No recommendations saved yet.")
    else:
        st.dataframe(log_df, use_container_width=True, hide_index=True, height=420)
        st.download_button(
            "Download log as CSV",
            log_df.to_csv(index=False).encode("utf-8"),
            "tennis_scanner_v6.1_log.csv",
            "text/csv",
        )
        c1, c2, c3 = st.columns(3)
        with c1:
            row_id = st.selectbox("Log row ID", [int(value) for value in log_df["id"].tolist()])
        with c2:
            result_value = st.selectbox("Result", ["WIN", "LOSS", "VOID", "OPEN"])
        with c3:
            pnl = st.number_input("Profit / loss ($)", value=0.0, step=0.01)
        update_col, delete_col = st.columns(2)
        with update_col:
            if st.button("Update result", use_container_width=True):
                update_result(int(row_id), result_value, pnl)
                st.rerun()
        with delete_col:
            if st.button("Delete selected row", use_container_width=True):
                delete_recommendation(int(row_id))
                st.rerun()

if page == "Polymarket search":
    st.subheader("Polymarket US public search")
    st.caption("Read-only. No wallet or trading credentials are used.")
    query = st.text_input("Search events and markets", "tennis", key="pm_query")
    if st.button("Search Polymarket", key="pm_search_button"):
        try:
            with st.spinner("Searching Polymarket..."):
                st.session_state["pm_search_results"] = search_us_markets(query, limit=30, pages=3)
        except Exception as exc:
            st.error(f"Could not search Polymarket: {exc}")
    results = st.session_state.get("pm_search_results", [])
    if results:
        st.dataframe(pd.DataFrame([
            {
                "Event": row.get("event_title"),
                "Market": row.get("market_title"),
                "Live": row.get("event_live"),
                "Price": extract_display_price(row),
                "Volume": row.get("volume"),
                "Slug": row.get("market_slug"),
            }
            for row in results
        ]), use_container_width=True, hide_index=True, height=430)

st.divider()
st.caption(
    "This dashboard is read-only. Live Polymarket US execution, when enabled, runs only inside the Railway worker."
)
