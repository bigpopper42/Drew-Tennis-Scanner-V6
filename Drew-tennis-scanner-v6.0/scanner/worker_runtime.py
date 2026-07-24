from __future__ import annotations

import hashlib
import json
import os
import signal
import socket
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import __version__
from .api_tennis import get_fixtures, get_live_snapshot, get_rankings
from .event_pipeline import build_pipeline, event_competition_group, event_key, event_league
from .live_scan import PlayerScanResult, scan_both_players
from .polymarket import (
    enrich_market_row,
    extract_bbo_prices,
    extract_display_price,
    infer_player_prices,
    match_tennis_market,
)
from .supabase_store import InsertResult, SupabaseStore, SupabaseStoreError


TRUE_VALUES = {"1", "true", "yes", "on", "y"}
FALSE_VALUES = {"0", "false", "no", "off", "n"}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(f"{name} must be true or false.")


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    try:
        value = default if raw in (None, "") else int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer.") from exc
    return max(minimum, min(maximum, value))


def _env_float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = os.getenv(name)
    try:
        value = default if raw in (None, "") else float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number.") from exc
    return max(minimum, min(maximum, value))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_json(event: str, **fields: Any) -> None:
    payload = {"timestamp": utc_now_iso(), "event": event, "version": __version__, **fields}
    print(json.dumps(payload, default=str, sort_keys=True), flush=True)


@dataclass(frozen=True)
class WorkerConfig:
    api_tennis_key: str
    supabase_url: str
    supabase_key: str
    timezone_name: str = "America/Phoenix"
    scan_interval_seconds: int = 30
    fixtures_fallback_interval_seconds: int = 300
    rankings_refresh_seconds: int = 21600
    market_cache_ttl_seconds: int = 1800
    unmatched_retry_seconds: int = 300
    market_search_pages: int = 2
    minimum_market_confidence: float = 80.0
    shadow_bankroll: float = 100.0
    max_events_per_cycle: int = 0
    max_pending_records: int = 5000
    outcome_check_interval_seconds: int = 300
    save_all_scans: bool = False
    dry_run: bool = False
    worker_id: str = ""
    railway_deployment_id: str = ""

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        api_key = str(os.getenv("API_TENNIS_KEY") or "").strip()
        supabase_key = str(
            os.getenv("SUPABASE_SECRET_KEY")
            or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
            or ""
        ).strip()
        dry_run = _env_bool("DRY_RUN", False)
        worker_id = str(
            os.getenv("WORKER_ID")
            or os.getenv("RAILWAY_SERVICE_NAME")
            or socket.gethostname()
            or "drew-tennis-worker"
        ).strip()
        config = cls(
            api_tennis_key=api_key,
            supabase_url=str(os.getenv("SUPABASE_URL") or "").strip(),
            supabase_key=supabase_key,
            timezone_name=str(os.getenv("TIMEZONE") or "America/Phoenix").strip(),
            scan_interval_seconds=_env_int("SCAN_INTERVAL_SECONDS", 30, 15, 3600),
            fixtures_fallback_interval_seconds=_env_int(
                "FIXTURES_FALLBACK_INTERVAL_SECONDS", 300, 60, 86400
            ),
            rankings_refresh_seconds=_env_int("RANKINGS_REFRESH_SECONDS", 21600, 300, 604800),
            market_cache_ttl_seconds=_env_int("MARKET_CACHE_TTL_SECONDS", 1800, 60, 86400),
            unmatched_retry_seconds=_env_int("UNMATCHED_RETRY_SECONDS", 300, 30, 86400),
            market_search_pages=_env_int("MARKET_SEARCH_PAGES", 2, 1, 5),
            minimum_market_confidence=_env_float("MIN_MARKET_CONFIDENCE", 80.0, 60.0, 100.0),
            shadow_bankroll=_env_float("SHADOW_BANKROLL", 100.0, 0.0, 1_000_000_000.0),
            max_events_per_cycle=_env_int("MAX_EVENTS_PER_CYCLE", 0, 0, 1000),
            max_pending_records=_env_int("MAX_PENDING_RECORDS", 5000, 100, 100000),
            outcome_check_interval_seconds=_env_int("OUTCOME_CHECK_INTERVAL_SECONDS", 300, 60, 86400),
            save_all_scans=False,
            dry_run=dry_run,
            worker_id=worker_id,
            railway_deployment_id=str(os.getenv("RAILWAY_DEPLOYMENT_ID") or "").strip(),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.api_tennis_key:
            raise ValueError("API_TENNIS_KEY is required.")
        if not self.timezone_name:
            raise ValueError("TIMEZONE cannot be empty.")
        if not self.dry_run:
            if not self.supabase_url:
                raise ValueError("SUPABASE_URL is required unless DRY_RUN=true.")
            if not self.supabase_key:
                raise ValueError(
                    "SUPABASE_SECRET_KEY or SUPABASE_SERVICE_ROLE_KEY is required unless DRY_RUN=true."
                )

    def public_summary(self) -> Dict[str, Any]:
        return {
            "timezone": self.timezone_name,
            "scan_interval_seconds": self.scan_interval_seconds,
            "fixtures_fallback_interval_seconds": self.fixtures_fallback_interval_seconds,
            "rankings_refresh_seconds": self.rankings_refresh_seconds,
            "market_cache_ttl_seconds": self.market_cache_ttl_seconds,
            "unmatched_retry_seconds": self.unmatched_retry_seconds,
            "minimum_market_confidence": self.minimum_market_confidence,
            "shadow_bankroll": self.shadow_bankroll,
            "max_events_per_cycle": self.max_events_per_cycle,
            "outcome_check_interval_seconds": self.outcome_check_interval_seconds,
            "stores_only_qualified_trades": True,
            "dry_run": self.dry_run,
            "worker_id": self.worker_id,
            "railway_deployment_id": self.railway_deployment_id,
        }


@dataclass
class MarketCacheEntry:
    row: Optional[Dict[str, Any]]
    expires_at: float
    candidates_found: int = 0
    reason: str = ""


@dataclass
class CycleReport:
    cycle_id: str
    started_at: str
    completed_at: str = ""
    duration_seconds: float = 0.0
    status: str = "RUNNING"
    api_events: int = 0
    supported_events: int = 0
    excluded_events: int = 0
    markets_matched: int = 0
    markets_unmatched: int = 0
    player_scans: int = 0
    trade_signals: int = 0
    inserted_scans: int = 0
    duplicate_scans: int = 0
    pending_scans: int = 0
    outcomes_resolved: int = 0
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    decision_counts: Dict[str, int] = field(default_factory=dict)
    snapshot_summary: Dict[str, Any] = field(default_factory=dict)
    pipeline_counts: Dict[str, int] = field(default_factory=dict)

    def metrics(self) -> Dict[str, Any]:
        return {
            "api_events": self.api_events,
            "supported_events": self.supported_events,
            "excluded_events": self.excluded_events,
            "markets_matched": self.markets_matched,
            "markets_unmatched": self.markets_unmatched,
            "player_scans": self.player_scans,
            "trade_signals": self.trade_signals,
            "inserted_scans": self.inserted_scans,
            "duplicate_scans": self.duplicate_scans,
            "pending_scans": self.pending_scans,
            "outcomes_resolved": self.outcomes_resolved,
            "decision_counts": dict(self.decision_counts),
            "snapshot": dict(self.snapshot_summary),
            "pipeline": dict(self.pipeline_counts),
        }

    def database_record(self, config: WorkerConfig) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "worker_id": config.worker_id,
            "worker_version": __version__,
            "started_at": self.started_at,
            "completed_at": self.completed_at or None,
            "duration_seconds": round(self.duration_seconds, 3),
            "status": self.status,
            "api_events": self.api_events,
            "supported_events": self.supported_events,
            "excluded_events": self.excluded_events,
            "markets_matched": self.markets_matched,
            "markets_unmatched": self.markets_unmatched,
            "player_scans": self.player_scans,
            "trade_signals": self.trade_signals,
            "inserted_scans": self.inserted_scans,
            "duplicate_scans": self.duplicate_scans,
            "errors": self.errors,
            "warnings": self.warnings,
            "metrics": self.metrics(),
        }


class RailwayShadowWorker:
    """Always-on API Tennis-first, Polymarket-matched shadow scanner."""

    def __init__(self, config: WorkerConfig, store: Optional[SupabaseStore] = None) -> None:
        self.config = config
        self.store = store
        if self.store is None and not config.dry_run:
            self.store = SupabaseStore(config.supabase_url, config.supabase_key)
        self.stop_event = threading.Event()
        self.market_cache: Dict[str, MarketCacheEntry] = {}
        self.ranking_cache: Dict[str, Dict[str, int]] = {}
        self.ranking_refreshed_at: Dict[str, float] = {}
        self.pending_records: List[Dict[str, Any]] = []
        self.last_fixture_fallback_at = 0.0
        self.last_outcome_check_at = 0.0
        self.recommendation_state: Dict[str, float] = {}
        self.started_at = utc_now_iso()

    def install_signal_handlers(self) -> None:
        def request_stop(signum: int, _frame: Any) -> None:
            log_json("shutdown_requested", signal=signum)
            self.stop_event.set()

        for sig in (signal.SIGTERM, signal.SIGINT):
            try:
                signal.signal(sig, request_stop)
            except (ValueError, OSError):
                pass

    def verify_startup(self) -> None:
        if self.store is not None:
            self.store.verify_tables()
        log_json("worker_ready", config=self.config.public_summary())
        self._heartbeat("READY", None, None, {})

    def run_forever(self) -> None:
        self.install_signal_handlers()
        self.verify_startup()
        while not self.stop_event.is_set():
            cycle_started = time.monotonic()
            try:
                report = self.run_cycle()
                log_json("cycle_complete", **report.metrics(), status=report.status, cycle_id=report.cycle_id)
            except Exception as exc:  # final safety net; the process stays alive
                log_json("cycle_crashed", error=str(exc))
                self._heartbeat("DEGRADED", None, str(exc), {})
            elapsed = time.monotonic() - cycle_started
            sleep_seconds = max(0.0, self.config.scan_interval_seconds - elapsed)
            self.stop_event.wait(sleep_seconds)
        self._heartbeat("STOPPED", None, None, {})
        log_json("worker_stopped")

    def run_cycle(self) -> CycleReport:
        monotonic_started = time.monotonic()
        report = CycleReport(cycle_id=str(uuid.uuid4()), started_at=utc_now_iso())
        self._heartbeat("RUNNING", report.cycle_id, None, {})
        self._safe_upsert_cycle(report)

        try:
            include_fixture_fallback = (
                monotonic_started - self.last_fixture_fallback_at
                >= self.config.fixtures_fallback_interval_seconds
            )
            snapshot = get_live_snapshot(
                self.config.api_tennis_key,
                timezone=self.config.timezone_name,
                include_live_fixtures_fallback=include_fixture_fallback,
            )
            if include_fixture_fallback:
                self.last_fixture_fallback_at = monotonic_started
            report.snapshot_summary = snapshot.summary()
            report.warnings.extend(snapshot.warnings)

            pipeline = build_pipeline(snapshot.events)
            report.pipeline_counts = dict(pipeline.counts)
            report.api_events = len(pipeline.all_events)
            report.supported_events = len(pipeline.supported_events)
            report.excluded_events = len(pipeline.excluded_events)

            events = pipeline.supported_events
            if self.config.max_events_per_cycle:
                events = events[: self.config.max_events_per_cycle]
                if len(pipeline.supported_events) > len(events):
                    report.warnings.append(
                        f"MAX_EVENTS_PER_CYCLE limited this cycle to {len(events)} of "
                        f"{len(pipeline.supported_events)} supported matches."
                    )

            rankings = self._rankings_for_events(events, report)
            current_records: List[Dict[str, Any]] = []
            for event in events:
                try:
                    event_records, market_found, event_counts = self._process_event(
                        event, rankings, report.cycle_id, report.started_at
                    )
                    for status, count in event_counts.items():
                        report.decision_counts[status] = report.decision_counts.get(status, 0) + count
                    current_records.extend(event_records)
                    if market_found:
                        report.markets_matched += 1
                    else:
                        report.markets_unmatched += 1
                except Exception as exc:
                    key = event_key(event)
                    report.errors.append(f"Event {key}: {exc}")
                    # Even when market lookup fails unexpectedly, preserve two
                    # price-less player scans whenever the mapping engine can run.
                    fallback = scan_both_players(event, rankings, bankroll=self.config.shadow_bankroll)
                    for result in fallback:
                        status = str(result.decision.status or "UNKNOWN")
                        report.decision_counts[status] = report.decision_counts.get(status, 0) + 1
                        if status == "TRADE":
                            current_records.append(
                                self._build_scan_record(
                                    event,
                                    result,
                                    report.cycle_id,
                                    report.started_at,
                                    market_row=None,
                                    market_side=None,
                                    market_price=0.0,
                                    extra_errors=[f"Event processing error: {exc}"],
                                )
                            )

            # Every player is evaluated, but Version 6.0 persists only qualified trades.
            report.player_scans = sum(
                int(value) for value in report.decision_counts.values()
            )
            report.trade_signals = report.decision_counts.get("TRADE", 0)

            insert_result = self._persist_records(current_records)
            report.inserted_scans = insert_result.inserted
            report.duplicate_scans = insert_result.duplicates
            report.pending_scans = len(self.pending_records)
            report.outcomes_resolved = self._resolve_open_trade_outcomes(monotonic_started, report)
            report.status = "SUCCESS" if not report.errors and not self.pending_records else "DEGRADED"
        except Exception as exc:
            report.status = "FAILED"
            report.errors.append(str(exc))
        finally:
            report.completed_at = utc_now_iso()
            report.duration_seconds = time.monotonic() - monotonic_started
            self._safe_upsert_cycle(report)
            self._heartbeat(
                report.status,
                report.cycle_id,
                report.errors[-1] if report.errors else None,
                report.metrics(),
                cycle_started_at=report.started_at,
                cycle_completed_at=report.completed_at,
                cycle_duration=report.duration_seconds,
            )
        return report

    def _rankings_for_events(
        self, events: Sequence[Dict[str, Any]], report: CycleReport
    ) -> Dict[str, int]:
        tours = {event_league(event) for event in events} & {"ATP"}
        now = time.monotonic()
        combined: Dict[str, int] = {}
        for tour in sorted(tours):
            stale = (
                tour not in self.ranking_cache
                or now - self.ranking_refreshed_at.get(tour, 0.0)
                >= self.config.rankings_refresh_seconds
            )
            if stale:
                try:
                    self.ranking_cache[tour] = get_rankings(self.config.api_tennis_key, tour)
                    self.ranking_refreshed_at[tour] = now
                except Exception as exc:
                    report.warnings.append(f"{tour} rankings unavailable: {exc}")
            combined.update(self.ranking_cache.get(tour, {}))
        return combined

    def _process_event(
        self,
        event: Dict[str, Any],
        rankings: Mapping[Any, Any],
        cycle_id: str,
        scanned_at: str,
    ) -> Tuple[List[Dict[str, Any]], bool, Dict[str, int]]:
        player1 = str(event.get("event_first_player") or "").strip()
        player2 = str(event.get("event_second_player") or "").strip()
        market_row = self._find_market(event)
        prices: Dict[str, float] = {}
        sides: Dict[str, Optional[str]] = {player1: None, player2: None}
        market_errors: List[str] = []
        market_timestamp: Optional[str] = None
        market_volume: Optional[float] = None
        market_liquidity: Optional[float] = None

        if market_row:
            try:
                market_row = enrich_market_row(market_row, include_bbo=True)
                bbo_prices = extract_bbo_prices(market_row.get("bbo_payload") or {})
                inferred = infer_player_prices(
                    market_row,
                    player1,
                    player2,
                    bbo_prices,
                    metadata_price=extract_display_price(market_row),
                )
                prices = dict(inferred.get("prices") or {})
                sides = dict(inferred.get("sides") or sides)
                market_timestamp = str(market_row.get("market_data_timestamp") or "") or None
                market_volume = market_row.get("volume")
                market_liquidity = market_row.get("liquidity")
                if not inferred.get("complete"):
                    market_errors.append(
                        "Polymarket was matched, but player-side prices could not be safely inferred for both players."
                    )
            except Exception as exc:
                market_errors.append(f"Polymarket pricing error: {exc}")

        scans = scan_both_players(
            event,
            rankings,
            price_by_player=prices,
            bankroll=self.config.shadow_bankroll,
            market_price_timestamp=market_timestamp,
            market_volume=market_volume,
            market_liquidity=market_liquidity,
        )
        records: List[Dict[str, Any]] = []
        counts: Dict[str, int] = {}
        for result in scans:
            status = str(result.decision.status or "UNKNOWN")
            counts[status] = counts.get(status, 0) + 1
            if status != "TRADE":
                continue
            records.append(
                self._build_scan_record(
                    event,
                    result,
                    cycle_id,
                    scanned_at,
                    market_row=market_row,
                    market_side=sides.get(result.player),
                    market_price=float(prices.get(result.player) or 0.0),
                    extra_errors=market_errors,
                )
            )
        return records, market_row is not None, counts

    def _find_market(self, event: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        key = self._market_cache_key(event)
        now = time.monotonic()
        cached = self.market_cache.get(key)
        if cached and cached.expires_at > now:
            return cached.row

        player1 = str(event.get("event_first_player") or "").strip()
        player2 = str(event.get("event_second_player") or "").strip()
        candidates = match_tennis_market(
            player1,
            player2,
            league=event_league(event),
            competition_group=event_competition_group(event),
            tournament=str(event.get("tournament_name") or ""),
            event_start=str(event.get("event_time") or ""),
            search_pages=self.config.market_search_pages,
            include_sport_fallback=True,
        )
        selected = self._select_market_candidate(candidates)
        ttl = (
            self.config.market_cache_ttl_seconds
            if selected is not None
            else self.config.unmatched_retry_seconds
        )
        self.market_cache[key] = MarketCacheEntry(
            row=selected,
            expires_at=now + ttl,
            candidates_found=len(candidates),
            reason="matched" if selected is not None else "no safe match-winner candidate",
        )
        return selected

    def _select_market_candidate(
        self, candidates: Sequence[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        for row in candidates:
            if not row.get("match_winner_market"):
                continue
            if row.get("closed") is True or row.get("active") is False:
                continue
            if not str(row.get("market_slug") or "").strip():
                continue
            try:
                confidence = float(row.get("api_match_confidence") or 0.0)
            except (TypeError, ValueError):
                confidence = 0.0
            if confidence < self.config.minimum_market_confidence:
                continue
            return dict(row)
        return None

    def _market_cache_key(self, event: Dict[str, Any]) -> str:
        return "|".join(
            [
                event_key(event),
                str(event.get("event_first_player") or "").strip().casefold(),
                str(event.get("event_second_player") or "").strip().casefold(),
                str(event.get("tournament_name") or "").strip().casefold(),
            ]
        )

    def _build_scan_record(
        self,
        event: Dict[str, Any],
        result: PlayerScanResult,
        cycle_id: str,
        scanned_at: str,
        *,
        market_row: Optional[Dict[str, Any]],
        market_side: Optional[str],
        market_price: float,
        extra_errors: Sequence[str],
    ) -> Dict[str, Any]:
        """Build one database row for a qualified trade only."""
        match = result.match
        decision = result.decision
        if decision.status != "TRADE":
            raise ValueError("Version 6.0 records only qualified trades.")

        market_row = market_row or {}
        mapping_errors = list(result.mapping.errors or [])
        if result.error:
            mapping_errors.append(result.error)
        mapping_errors.extend(str(item) for item in extra_errors if item)
        warnings = list(dict.fromkeys(list(result.mapping.warnings or []) + list(decision.concerns or [])))

        event_state = {
            "event_final_result": event.get("event_final_result"),
            "event_game_result": event.get("event_game_result"),
            "event_status": event.get("event_status"),
            "event_serve": event.get("event_serve"),
            "scores": event.get("scores") or [],
            "pointbypoint_games": len(event.get("pointbypoint") or []),
            "statistics_rows": len(event.get("statistics") or []),
        }
        market_metadata = {
            "event_id": market_row.get("event_id"),
            "event_title": market_row.get("event_title"),
            "event_slug": market_row.get("event_slug"),
            "match_winner_score": market_row.get("match_winner_score"),
            "market_confidence": market_row.get("market_confidence"),
            "pair_similarity": market_row.get("api_pair_similarity"),
            "tournament_similarity": market_row.get("api_tournament_similarity"),
            "active": market_row.get("active"),
            "closed": market_row.get("closed"),
            "best_bid_cents": market_row.get("best_bid_cents"),
            "best_ask_cents": market_row.get("best_ask_cents"),
            "current_cents": market_row.get("current_cents"),
            "last_trade_cents": market_row.get("last_trade_cents"),
            "volume": match.market_volume,
            "liquidity": match.market_liquidity,
        }

        stable_event_key = str(match.event_key or event_key(event))
        trade_key = f"{stable_event_key}|{match.player.strip().casefold()}"
        prior_pct = self.recommendation_state.get(trade_key)
        if prior_pct is None:
            recommendation_change = "INITIAL"
        elif decision.stake_pct > prior_pct:
            recommendation_change = "UPGRADE"
        elif decision.stake_pct < prior_pct:
            recommendation_change = "DOWNGRADE"
        else:
            recommendation_change = "UNCHANGED"
        self.recommendation_state[trade_key] = decision.stake_pct

        record: Dict[str, Any] = {
            "scanned_at": scanned_at,
            "cycle_id": cycle_id,
            "worker_id": self.config.worker_id,
            "worker_version": __version__,
            "event_key": stable_event_key,
            "event_date": event.get("event_date"),
            "event_time": event.get("event_time"),
            "player": match.player,
            "opponent": match.opponent,
            "tournament": match.tournament,
            "event_type": str(event.get("event_type_type") or "Unknown"),
            "league": match.league,
            "competition_group": match.competition_group,
            "api_source": str(event.get("_api_source") or match.api_source or "get_livescore"),
            "event_status": event.get("event_status"),
            "event_final_result": event.get("event_final_result"),
            "event_game_result": event.get("event_game_result"),
            "event_serve": event.get("event_serve"),
            "event_state": event_state,
            "market_found": bool(market_row),
            "market_id": market_row.get("market_id"),
            "market_slug": market_row.get("market_slug"),
            "market_title": market_row.get("market_title"),
            "market_lookup_source": market_row.get("lookup_source"),
            "market_match_confidence": market_row.get("api_match_confidence"),
            "market_side": market_side,
            "market_price_cents": round(float(market_price or 0.0), 2),
            "market_price_timestamp": match.market_price_timestamp,
            "market_volume": match.market_volume,
            "market_liquidity": match.market_liquidity,
            "market_metadata": market_metadata,
            "decision_status": decision.status,
            "decision_reason": decision.reason,
            "stability_score": decision.score,
            "required_score": 75.0,
            "stake_pct": decision.stake_pct,
            "stake_amount": decision.stake_amount,
            "bankroll": match.bankroll,
            "data_completeness_pct": decision.data_completeness_pct,
            "core_completeness_pct": decision.core_completeness_pct,
            "scoring_completeness_pct": decision.scoring_completeness_pct,
            "best_of_sets": match.best_of_sets,
            "match_closing_set": match.match_closing_set,
            "straight_set_closing": match.straight_set_closing,
            "deciding_set": match.deciding_set,
            "break_lead": match.break_lead,
            "serving": match.serving,
            "serving_for_match": match.serving_for_match,
            "tiebreak": match.tiebreak,
            "backed_player_games_in_set": match.backed_player_games_in_set,
            "opponent_games_in_set": match.opponent_games_in_set,
            "current_game_score": match.current_game_score,
            "completed_sets": match.completed_sets,
            "breaks_suffered_by_set": match.breaks_suffered_by_set,
            "breaks_suffered_total": match.breaks_suffered_total,
            "current_set_breaks_suffered": match.current_set_breaks_suffered,
            "service_points_won_pct": match.service_points_won_pct,
            "current_set_service_points_won_pct": match.current_set_service_points_won_pct,
            "effective_service_points_won_pct": match.effective_service_points_won_pct,
            "opponent_service_points_won_pct": match.opponent_service_points_won_pct,
            "opponent_current_set_service_points_won_pct": match.opponent_current_set_service_points_won_pct,
            "first_serve_points_won_pct": match.first_serve_points_won_pct,
            "current_set_first_serve_points_won_pct": match.current_set_first_serve_points_won_pct,
            "first_serve_in_pct": match.first_serve_in_pct,
            "current_set_first_serve_in_pct": match.current_set_first_serve_in_pct,
            "break_points_created": match.break_points_created,
            "break_points_faced": match.break_points_faced,
            "comfortable_holds_pct": match.comfortable_holds_pct,
            "double_faults_per_service_game": match.double_faults_per_service_game,
            "ranking": match.ranking,
            "opponent_ranking": match.opponent_ranking,
            "trade_key": trade_key,
            "recommendation_change": recommendation_change,
            "alert_eligible": recommendation_change in {"INITIAL", "UPGRADE"},
            "warnings": warnings,
            "errors": list(dict.fromkeys(mapping_errors)),
            "score_parts": decision.score_parts,
            "factor_availability": decision.factor_availability,
            "field_provenance": match.field_provenance,
            "match_snapshot": match.to_dict(),
            "paper_trade_status": "OPEN",
            "paper_entry_price_cents": round(float(market_price or 0.0), 2) or None,
            "paper_stake_amount": decision.stake_amount,
            "paper_result": "OPEN",
            "paper_pnl": 0.0,
        }
        record["dedupe_key"] = self._dedupe_key(record)
        return record

    @staticmethod
    def _dedupe_key(record: Mapping[str, Any]) -> str:
        # One qualified row per player per scan cycle. Market price is excluded:
        # it is informational and must never affect trading identity.
        state = {
            "cycle_id": record.get("cycle_id"),
            "event_key": record.get("event_key"),
            "player": record.get("player"),
        }
        encoded = json.dumps(state, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _persist_records(self, current_records: Sequence[Dict[str, Any]]) -> InsertResult:
        combined = [
            row
            for row in list(self.pending_records) + list(current_records)
            if row.get("decision_status") == "TRADE"
        ]
        if not combined:
            self.pending_records = []
            return InsertResult(attempted=0, inserted=0)
        if self.config.dry_run or self.store is None:
            self.pending_records = []
            return InsertResult(attempted=len(combined), inserted=len(combined))
        try:
            result = self.store.insert_shadow_scans(combined)
            self.pending_records = []
            return result
        except Exception as exc:
            self.pending_records = combined[-self.config.max_pending_records :]
            log_json("supabase_insert_failed", error=str(exc), queued_records=len(self.pending_records))
            return InsertResult(attempted=0, inserted=0)

    @staticmethod
    def _fixture_winner(event: Mapping[str, Any]) -> Tuple[Optional[str], Optional[str]]:
        first = str(event.get("event_first_player") or "").strip()
        second = str(event.get("event_second_player") or "").strip()
        raw_winner = str(event.get("event_winner") or "").strip()
        normalized = raw_winner.casefold()
        if normalized in {"first player", "first", "1", first.casefold()} and first:
            return first, str(event.get("event_final_result") or "") or None
        if normalized in {"second player", "second", "2", second.casefold()} and second:
            return second, str(event.get("event_final_result") or "") or None

        score = str(event.get("event_final_result") or "").replace("–", "-")
        parts = [part.strip() for part in score.split("-")]
        if len(parts) == 2:
            try:
                first_sets, second_sets = int(parts[0]), int(parts[1])
                if first_sets > second_sets and first:
                    return first, score
                if second_sets > first_sets and second:
                    return second, score
            except ValueError:
                pass
        return None, score or None

    def _resolve_open_trade_outcomes(self, now_monotonic: float, report: CycleReport) -> int:
        if self.config.dry_run or self.store is None:
            return 0
        if now_monotonic - self.last_outcome_check_at < self.config.outcome_check_interval_seconds:
            return 0
        self.last_outcome_check_at = now_monotonic
        try:
            open_rows = self.store.fetch_open_trades(limit=1000)
        except Exception as exc:
            report.warnings.append(f"Outcome lookup could not read open trades: {exc}")
            return 0
        if not open_rows:
            return 0

        dates = sorted({str(row.get("event_date") or "").strip() for row in open_rows if row.get("event_date")})
        if not dates:
            dates = [datetime.now(timezone.utc).date().isoformat()]
        fixtures: Dict[str, Dict[str, Any]] = {}
        for date_value in dates:
            try:
                for event in get_fixtures(
                    self.config.api_tennis_key,
                    date_value,
                    timezone=self.config.timezone_name,
                ):
                    fixtures[str(event.get("event_key") or event.get("match_key") or "")] = event
            except Exception as exc:
                report.warnings.append(f"Outcome fixtures unavailable for {date_value}: {exc}")

        resolved = 0
        for row in open_rows:
            fixture = fixtures.get(str(row.get("event_key") or ""))
            if not fixture:
                continue
            winner, final_score = self._fixture_winner(fixture)
            if not winner:
                continue
            player = str(row.get("player") or "").strip()
            result = "WIN" if player.casefold() == winner.casefold() else "LOSS"
            stake = float(row.get("paper_stake_amount") or 0.0)
            entry = float(row.get("paper_entry_price_cents") or row.get("market_price_cents") or 0.0)
            if result == "WIN" and entry > 0:
                pnl = round(stake * (100.0 / entry - 1.0), 2)
            elif result == "LOSS":
                pnl = round(-stake, 2)
            else:
                pnl = 0.0
            try:
                self.store.resolve_trade(
                    row.get("id"),
                    {
                        "paper_trade_status": "RESOLVED",
                        "paper_result": result,
                        "paper_pnl": pnl,
                        "final_winner": winner,
                        "final_score": final_score,
                        "resolved_at": utc_now_iso(),
                    },
                )
                resolved += 1
            except Exception as exc:
                report.warnings.append(f"Could not resolve trade row {row.get('id')}: {exc}")
        return resolved

    def _safe_upsert_cycle(self, report: CycleReport) -> None:
        if self.config.dry_run or self.store is None:
            return
        try:
            self.store.upsert_cycle(report.database_record(self.config))
        except Exception as exc:
            log_json("cycle_status_write_failed", cycle_id=report.cycle_id, error=str(exc))

    def _heartbeat(
        self,
        status: str,
        cycle_id: Optional[str],
        last_error: Optional[str],
        metrics: Mapping[str, Any],
        *,
        cycle_started_at: Optional[str] = None,
        cycle_completed_at: Optional[str] = None,
        cycle_duration: Optional[float] = None,
    ) -> None:
        if self.config.dry_run or self.store is None:
            return
        record = {
            "worker_id": self.config.worker_id,
            "version": __version__,
            "status": status,
            "started_at": self.started_at,
            "last_seen_at": utc_now_iso(),
            "last_cycle_id": cycle_id,
            "last_cycle_started_at": cycle_started_at,
            "last_cycle_completed_at": cycle_completed_at,
            "last_cycle_duration_seconds": round(cycle_duration, 3)
            if cycle_duration is not None
            else None,
            "last_error": last_error,
            "metrics": dict(metrics),
            "railway_deployment_id": self.config.railway_deployment_id or None,
            "updated_at": utc_now_iso(),
        }
        try:
            self.store.upsert_worker_status(record)
        except Exception as exc:
            log_json("heartbeat_write_failed", error=str(exc), status=status)
