"""Guarded Polymarket US execution for approved scanner trade records.

The tennis scanner remains the sole decision maker. This module independently
validates the selected Polymarket US market, sizes one market order from the
authenticated account balance, previews it, submits it, and reports the result.
"""

from __future__ import annotations

import math
import re
import time
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .market_validation import (
    is_match_winner_moneyline,
    market_question,
    sports_market_type,
)
from .polymarket import match_tennis_market


OPEN_MARKET_STATE = "MARKET_STATE_OPEN"
LONG_SIDE = "Long / YES"
SHORT_SIDE = "Short / NO"


class ExecutionClient(Protocol):
    account: Any
    markets: Any
    orders: Any
    portfolio: Any
    search: Any

    def close(self) -> None: ...


@dataclass(frozen=True)
class ExecutionConfig:
    key_id: str
    secret_key: str
    bankroll_pct: float = 20.0
    minimum_order_usd: float = 0.50
    minimum_price_cents: float = 50.0
    maximum_price_cents: float = 99.0
    slippage_ticks: int = 1
    minimum_market_confidence: float = 80.0


@dataclass(frozen=True)
class ExecutionResult:
    status: str
    reason: str
    signal_key: str
    player: str
    opponent: str
    market_slug: str = ""
    market_side: str = ""
    market_question: str = ""
    market_type: str = ""
    bankroll_pct: float = 20.0
    account_balance: float = 0.0
    buying_power: float = 0.0
    stake_amount: float = 0.0
    player_price_cents: float = 0.0
    order_id: str = ""
    order_state: str = ""
    filled_quantity: float = 0.0
    recommendation_change: str = ""
    retryable: bool = False
    diagnostic_stage: str = ""

    @property
    def order_created(self) -> bool:
        return self.status == "EXECUTED"

    def log_fields(self) -> dict[str, Any]:
        return {
            "execution_status": self.status,
            "execution_reason": self.reason,
            "signal_key": self.signal_key,
            "player": self.player,
            "opponent": self.opponent,
            "market_slug": self.market_slug,
            "market_side": self.market_side,
            "market_question": self.market_question,
            "market_type": self.market_type,
            "bankroll_pct": self.bankroll_pct,
            "account_balance": self.account_balance,
            "buying_power": self.buying_power,
            "stake_amount": self.stake_amount,
            "player_price_cents": self.player_price_cents,
            "order_id": self.order_id,
            "order_state": self.order_state,
            "filled_quantity": self.filled_quantity,
            "recommendation_change": self.recommendation_change,
            "retryable": self.retryable,
            "diagnostic_stage": self.diagnostic_stage,
        }


class PolymarketExecutionEngine:
    """Place one guarded order per signal while allowing distinct open markets."""

    def __init__(
        self,
        config: ExecutionConfig,
        *,
        client: ExecutionClient | None = None,
    ) -> None:
        self.config = config
        if client is not None:
            self.client = client
        else:
            # Imported lazily so read-only/test environments can import the
            # scanner without the trading SDK. Railway installs it from
            # requirements.txt before live execution starts.
            from polymarket_us import PolymarketUS

            self.client = PolymarketUS(
                key_id=config.key_id,
                secret_key=config.secret_key,
                timeout=20.0,
            )

    def close(self) -> None:
        self.client.close()

    def execute_trade(self, record: Mapping[str, Any]) -> ExecutionResult:
        player = str(record.get("player") or "").strip()
        opponent = str(record.get("opponent") or "").strip()
        signal_key = self.signal_key(record)
        market_slug = str(record.get("market_slug") or "").strip()
        market_side = str(record.get("market_side") or "").strip()
        authenticated_market_question = ""
        authenticated_market_type = ""
        recommendation_change = str(record.get("recommendation_change") or "").strip().upper()
        diagnostic_stage = "precheck"
        order_submission_started = False

        def reject(reason: str, *, retryable: bool = False, stage: str = "", **fields: Any) -> ExecutionResult:
            result_fields: dict[str, Any] = {
                "status": "REJECTED",
                "reason": reason,
                "signal_key": signal_key,
                "player": player,
                "opponent": opponent,
                "market_slug": market_slug,
                "market_side": market_side,
                "market_question": authenticated_market_question,
                "market_type": authenticated_market_type,
                "bankroll_pct": self.config.bankroll_pct,
                "recommendation_change": recommendation_change,
                "retryable": retryable,
                "diagnostic_stage": stage or diagnostic_stage,
            }
            result_fields.update(fields)
            return ExecutionResult(**result_fields)

        if record.get("decision_status") != "TRADE":
            return reject("Scanner record is not an approved TRADE.")
        if not record.get("alert_eligible"):
            return reject("Scanner record is not eligible for a new trade alert.")
        try:
            confidence = float(record.get("market_match_confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0

        try:
            # Discovery is only a recall step. Build an ordered list of possible
            # slugs, then let the SDK market payload decide which one is the real
            # two-player moneyline. This avoids two failure modes:
            #   1. a worker miss causing an immediate rejection; and
            #   2. the first incomplete/prop search result hiding a valid
            #      moneyline later in the ranked result set.
            candidate_rows: list[dict[str, Any]] = []
            seen_slugs: set[str] = set()

            def add_candidate(slug: Any, score: Any, side: Any = "") -> None:
                candidate_slug = str(slug or "").strip()
                if not candidate_slug or candidate_slug in seen_slugs:
                    return
                try:
                    candidate_confidence = float(score or 0.0)
                except (TypeError, ValueError):
                    candidate_confidence = 0.0
                # Public-search confidence is ranking information only. It is
                # never a safety gate; the authenticated market payload below
                # decides whether a candidate is the correct two-player moneyline.
                seen_slugs.add(candidate_slug)
                candidate_rows.append(
                    {
                        "market_slug": candidate_slug,
                        "api_match_confidence": candidate_confidence,
                        "market_side": str(side or "").strip(),
                    }
                )

            add_candidate(market_slug, confidence, market_side)

            diagnostic_stage = "sdk_discovery"
            discovery_errors: list[str] = []
            for candidate in self._sdk_market_candidates(player, opponent):
                add_candidate(
                    candidate.get("market_slug"),
                    candidate.get("api_match_confidence", 100.0),
                    candidate.get("market_side", ""),
                )
            if not candidate_rows:
                discovery_errors.append("official SDK search returned no candidate slugs")

            # Always refresh when the worker missed or only had a provisional
            # public candidate. A strict public moneyline can use its known slug
            # directly, preserving the fast path for normal matches.
            needs_fresh_lookup = (
                not market_slug
                or bool(record.get("market_discovery_candidate"))
                or not bool(record.get("market_public_moneyline_confirmed", True))
            )
            if needs_fresh_lookup:
                try:
                    fallback_candidates = match_tennis_market(
                        player,
                        opponent,
                        league=str(record.get("league") or ""),
                        competition_group=str(record.get("competition_group") or ""),
                        tournament=str(record.get("tournament") or ""),
                        event_start=str(record.get("event_time") or ""),
                        include_sport_fallback=True,
                    )
                except Exception as exc:
                    discovery_errors.append(f"public fallback failed: {exc}")
                    fallback_candidates = []
                for row in fallback_candidates:
                    add_candidate(
                        row.get("market_slug"),
                        row.get("api_match_confidence"),
                        row.get("market_side"),
                    )

            if not candidate_rows:
                detail = "; ".join(discovery_errors) or "no candidate slugs were returned"
                return reject(
                    f"Market discovery returned no candidate slugs ({detail}).",
                    retryable=True,
                    stage="discovery",
                )

            diagnostic_stage = "authenticated_market_validation"
            market: dict[str, Any] = {}
            single_candidate_failure = ""
            for candidate in candidate_rows:
                candidate_slug = str(candidate["market_slug"])
                try:
                    market_payload = self.client.markets.retrieve_by_slug(
                        candidate_slug
                    )
                except Exception as exc:
                    single_candidate_failure = f"retrieve_failed:{exc}"
                    continue

                candidate_market = _market_payload(market_payload)
                if not candidate_market:
                    single_candidate_failure = "empty"
                    continue
                authenticated_market_question = market_question(candidate_market)
                authenticated_market_type = sports_market_type(candidate_market)
                if (
                    candidate_market.get("active") is not True
                    or candidate_market.get("closed") is True
                ):
                    single_candidate_failure = "inactive"
                    continue
                if not is_match_winner_moneyline(candidate_market):
                    single_candidate_failure = "not_moneyline"
                    continue
                if not self._market_names_match(
                    candidate_market, player, opponent
                ):
                    single_candidate_failure = "name_mismatch"
                    continue

                market_slug = candidate_slug
                confidence = float(candidate["api_match_confidence"])
                market_side = str(
                    candidate.get("market_side") or market_side
                ).strip()
                market = candidate_market
                authenticated_market_question = market_question(market)
                authenticated_market_type = sports_market_type(market)
                break

            if not market:
                # Preserve the precise legacy reason when the scanner supplied a
                # single explicit slug. For lookup recovery, report that every
                # candidate failed authenticated validation rather than claiming
                # no public match existed.
                if len(candidate_rows) == 1 and market_slug:
                    if single_candidate_failure == "empty":
                        return reject(
                            "Polymarket US did not return the matched market."
                        )
                    if single_candidate_failure == "inactive":
                        return reject(
                            "Polymarket market is not active and tradable."
                        )
                    if single_candidate_failure == "not_moneyline":
                        return reject(
                            "Authenticated Polymarket market is not the match-winner moneyline."
                        )
                    if single_candidate_failure == "name_mismatch":
                        return reject(
                            "Live market names do not match the scanner signal."
                        )
                return reject(
                    "No authenticated Polymarket match-winner market matched both players "
                    f"(last validation result: {single_candidate_failure or 'unknown'}; "
                    f"candidates checked: {len(candidate_rows)}).",
                    retryable=single_candidate_failure.startswith("retrieve_failed"),
                    stage="authenticated_market_validation",
                )

            # Multiple unrelated markets are always allowed. A same-market
            # position is allowed only for a scanner-approved UPGRADE so the
            # stronger signal can add to the existing position. An unfinished
            # same-market order still blocks execution to prevent overlapping
            # submissions before the first order has a final state.
            open_orders = self._list_open_orders_for_market(market_slug)
            if self._has_open_order_for_market(open_orders, market_slug):
                return reject(
                    "An order for this same Polymarket market is still open."
                )

            positions = self.client.portfolio.positions(
                {"market": market_slug, "limit": 100}
            )
            has_same_market_position = self._has_open_position_for_market(
                positions, market_slug
            )
            if has_same_market_position and recommendation_change != "UPGRADE":
                return reject(
                    "A position for this same Polymarket market already exists."
                )

            # Never trust a stale discovery-side value for live money. The
            # authenticated marketSides payload must map both competitors to
            # opposite LONG/SHORT contracts before an order can be created.
            live_market_side = self._live_market_side(market, player, opponent)
            if live_market_side not in {LONG_SIDE, SHORT_SIDE}:
                return reject("Backed player could not be mapped safely to YES or NO.")
            market_side = live_market_side

            minimum_trade_qty = self._minimum_trade_qty(market)
            tick_size = self._tick_size(market)

            diagnostic_stage = "order_book"
            raw_book = self.client.markets.book(market_slug) or {}
            book = _market_data(raw_book)
            if not book:
                return reject("Polymarket US returned no usable order-book data.")
            book_state = str(book.get("state") or "").strip().upper()
            if not book_state:
                return reject("Polymarket order-book state was missing from the API response.")
            if book_state not in {OPEN_MARKET_STATE, "OPEN"}:
                return reject(
                    f"Polymarket order book is not open (reported state: {book_state})."
                )

            long_reference, player_price = self._execution_prices(book, market_side)
            player_price_cents = round(player_price * 100.0, 2)
            if not (
                self.config.minimum_price_cents
                <= player_price_cents
                <= self.config.maximum_price_cents
            ):
                return reject(
                    "Live player price is outside the configured execution range.",
                    player_price_cents=player_price_cents,
                )

            account_balance, buying_power = self._account_usd_balance(
                self.client.account.balances()
            )
            stake_amount = self._stake_amount(account_balance, buying_power)
            estimated_contracts = stake_amount / max(player_price, 1e-9)
            if minimum_trade_qty is not None and estimated_contracts + 1e-9 < minimum_trade_qty:
                return reject(
                    "Calculated order is below this market's minimum contract quantity.",
                    account_balance=account_balance,
                    buying_power=buying_power,
                    stake_amount=stake_amount,
                    player_price_cents=player_price_cents,
                    stage="order_sizing",
                )
            if stake_amount < self.config.minimum_order_usd:
                return reject(
                    f"Calculated {self.config.bankroll_pct:g}% stake is below the minimum live order.",
                    account_balance=account_balance,
                    buying_power=buying_power,
                    stake_amount=stake_amount,
                    player_price_cents=player_price_cents,
                )
            diagnostic_stage = "order_preview"
            reference_price = self._round_to_tick(player_price, tick_size)
            order_request = {
                "marketSlug": market_slug,
                "intent": (
                    "ORDER_INTENT_BUY_LONG"
                    if market_side == LONG_SIDE
                    else "ORDER_INTENT_BUY_SHORT"
                ),
                "type": "ORDER_TYPE_MARKET",
                "cashOrderQty": {
                    "value": f"{stake_amount:.2f}",
                    "currency": "USD",
                },
                "tif": "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
                "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
                "synchronousExecution": True,
                "maxBlockTime": "5",
                "slippageTolerance": {
                    "currentPrice": {
                        "value": self._price_string(reference_price),
                        "currency": "USD",
                    },
                    "ticks": self.config.slippage_ticks,
                },
            }

            # Preview validates the exact request without moving money. The
            # released SDK has used both direct and wrapped preview payloads,
            # so the helper preserves compatibility without weakening checks.
            preview = self._preview_order(order_request)
            self._validate_preview(preview)
            diagnostic_stage = "order_submission"
            order_submission_started = True
            response = self.client.orders.create(order_request) or {}
            order_submission_started = False
        except Exception as exc:
            return ExecutionResult(
                status="FAILED",
                reason=f"Polymarket API request failed: {exc}",
                signal_key=signal_key,
                player=player,
                opponent=opponent,
                market_slug=market_slug,
                market_side=market_side,
                market_question=authenticated_market_question,
                market_type=authenticated_market_type,
                bankroll_pct=self.config.bankroll_pct,
                recommendation_change=recommendation_change,
                retryable=not order_submission_started,
                diagnostic_stage=diagnostic_stage,
            )

        order_id = self._order_id(response)
        verified_response, verification_error = self._verify_order_status(
            order_id, response
        )
        execution_status, order_state, reason, filled_quantity = (
            self._interpret_order_response(verified_response)
        )
        if execution_status == "PENDING" and verification_error:
            reason = (
                "Order was submitted, but Polymarket status could not be "
                f"confirmed: {verification_error}"
            )
        return ExecutionResult(
            status=execution_status,
            reason=reason,
            signal_key=signal_key,
            player=player,
            opponent=opponent,
            market_slug=market_slug,
            market_side=market_side,
            market_question=authenticated_market_question,
            market_type=authenticated_market_type,
            bankroll_pct=self.config.bankroll_pct,
            account_balance=account_balance,
            buying_power=buying_power,
            stake_amount=stake_amount,
            player_price_cents=player_price_cents,
            order_id=order_id,
            order_state=order_state,
            filled_quantity=filled_quantity,
            recommendation_change=recommendation_change,
            retryable=False,
            diagnostic_stage="order_verification",
        )

    def _sdk_market_candidates(self, player: str, opponent: str) -> list[dict[str, Any]]:
        """Use the official SDK search endpoint before legacy HTTP discovery.

        Search responses contain events with nested markets. We collect slugs
        broadly, then require authenticated retrieval, active/open state,
        moneyline type, and exact two-player side assignment before execution.
        """
        search_api = getattr(self.client, "search", None)
        query_method = getattr(search_api, "query", None)
        if not callable(query_method):
            return []
        queries = [
            f"{player} {opponent}",
            f"{opponent} {player}",
            f"{_last_name(player)} {_last_name(opponent)}",
        ]
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for query in queries:
            if not query.strip():
                continue
            try:
                payload = query_method({"query": query, "limit": 50}) or {}
            except TypeError:
                payload = query_method({"query": query}) or {}
            except Exception:
                continue
            for market in _extract_market_mappings(payload):
                slug = str(market.get("slug") or market.get("marketSlug") or "").strip()
                if not slug or slug in seen:
                    continue
                seen.add(slug)
                rows.append({"market_slug": slug, "api_match_confidence": 100.0})
        return rows

    @staticmethod
    def _minimum_trade_qty(market: Mapping[str, Any]) -> float | None:
        for source in (market, market.get("marketData"), market.get("instrument")):
            if not isinstance(source, Mapping):
                continue
            for key in ("minimumTradeQty", "minimum_trade_qty", "minOrderSize"):
                try:
                    value = float(source.get(key))
                except (TypeError, ValueError):
                    continue
                if value > 0:
                    return value
        return None

    @staticmethod
    def _tick_size(market: Mapping[str, Any]) -> float:
        for source in (market, market.get("marketData"), market.get("instrument")):
            if not isinstance(source, Mapping):
                continue
            for key in ("orderPriceMinTickSize", "tickSize", "tick_size"):
                try:
                    value = float(source.get(key))
                except (TypeError, ValueError):
                    continue
                if 0 < value < 1:
                    return value
        return 0.01

    @staticmethod
    def _round_to_tick(price: float, tick_size: float) -> float:
        ticks = round(price / tick_size)
        return min(0.9999, max(tick_size, ticks * tick_size))

    @staticmethod
    def _validate_preview(preview: Mapping[str, Any]) -> None:
        if not preview:
            raise ValueError("Polymarket returned an empty order preview.")
        text = " ".join(
            str(preview.get(key) or "")
            for key in ("error", "message", "reason", "rejectReason", "orderRejectReason")
        ).strip()
        state = str(preview.get("state") or preview.get("status") or "").upper()
        if text and any(token in text.lower() for token in ("reject", "invalid", "error", "failed")):
            raise ValueError(f"Polymarket order preview rejected the request: {text}")
        if "REJECT" in state or "INVALID" in state or "FAIL" in state:
            raise ValueError(f"Polymarket order preview returned state {state}.")

    @staticmethod
    def signal_key(record: Mapping[str, Any]) -> str:
        base = str(
            record.get("trade_key")
            or f"{record.get('event_key')}|{str(record.get('player') or '').casefold()}"
        )
        change = str(record.get("recommendation_change") or "INITIAL").strip().upper()
        try:
            stake_tier = f"{float(record.get('stake_pct') or 0.0):g}"
        except (TypeError, ValueError):
            stake_tier = "unknown"
        # Initial and each scanner-approved upgrade are distinct signals;
        # unchanged rescans at the same tier retain the same key.
        return f"{base}|{change}|{stake_tier}"

    def _list_open_orders_for_market(self, market_slug: str) -> Mapping[str, Any]:
        try:
            payload = self.client.orders.list({"slugs": [market_slug]})
        except TypeError:
            # Compatibility with older SDK releases that accepted no params.
            payload = self.client.orders.list()
        return payload if isinstance(payload, Mapping) else {}

    @staticmethod
    def _has_open_order_for_market(
        payload: Mapping[str, Any], market_slug: str
    ) -> bool:
        expected = str(market_slug or "").strip().casefold()
        for order in list(payload.get("orders") or []):
            if not isinstance(order, Mapping):
                continue
            metadata = order.get("marketMetadata") or {}
            metadata_slug = metadata.get("slug") if isinstance(metadata, Mapping) else ""
            candidate = str(
                order.get("marketSlug")
                or order.get("market_slug")
                or metadata_slug
            ).strip().casefold()
            if candidate and candidate == expected:
                return True
        return False

    @staticmethod
    def _has_open_position_for_market(
        payload: Mapping[str, Any], market_slug: str
    ) -> bool:
        expected = str(market_slug or "").strip().casefold()
        positions = payload.get("positions") or {}
        if isinstance(positions, Mapping):
            iterable = positions.items()
        else:
            iterable = (("", item) for item in positions or [])

        for key, position in iterable:
            if not isinstance(position, Mapping) or position.get("expired") is True:
                continue
            metadata = position.get("marketMetadata") or {}
            metadata_slug = metadata.get("slug") if isinstance(metadata, Mapping) else ""
            candidate = str(
                key
                or position.get("marketSlug")
                or position.get("market_slug")
                or metadata_slug
            ).strip().casefold()
            if candidate != expected:
                continue
            raw = position.get("netPosition")
            try:
                return abs(float(raw or 0.0)) > 0.000001
            except (TypeError, ValueError):
                return True
        return False

    @staticmethod
    def _live_market_side(
        market: Mapping[str, Any], player: str, opponent: str
    ) -> str | None:
        assignment = _structured_side_assignment(market, player, opponent)
        if assignment is None:
            return None
        player_index, _opponent_index, sides = assignment
        return LONG_SIDE if sides[player_index]["long"] is True else SHORT_SIDE

    @staticmethod
    def _market_names_match(
        market: Mapping[str, Any], player: str, opponent: str
    ) -> bool:
        structured_sides = _structured_market_sides(market)
        if structured_sides:
            return _structured_side_assignment(market, player, opponent) is not None

        haystack = _normalize(
            " ".join(
                [
                    str(market.get("title") or ""),
                    str(market.get("question") or ""),
                    str(market.get("slug") or ""),
                    str(market.get("description") or ""),
                ]
            )
        )
        return _surname_matches(player, haystack) and _surname_matches(
            opponent, haystack
        )

    @staticmethod
    def _execution_prices(
        book: Mapping[str, Any], market_side: str
    ) -> tuple[float, float]:
        bids = [
            value
            for level in (book.get("bids") or [])
            if (value := _amount_value(level.get("px") if isinstance(level, Mapping) else None))
            is not None
        ]
        offers = [
            value
            for level in (book.get("offers") or [])
            if (value := _amount_value(level.get("px") if isinstance(level, Mapping) else None))
            is not None
        ]
        if market_side == LONG_SIDE:
            if not offers:
                raise ValueError("No executable YES offer is available.")
            long_reference = min(offers)
            return long_reference, long_reference
        if not bids:
            raise ValueError("No executable NO offer is available.")
        long_reference = max(bids)
        return long_reference, 1.0 - long_reference

    @staticmethod
    def _account_usd_balance(payload: Mapping[str, Any]) -> tuple[float, float]:
        balances = list(payload.get("balances") or [])
        selected: Mapping[str, Any] = {}
        for balance in balances:
            if not isinstance(balance, Mapping):
                continue
            if str(balance.get("currency") or "").upper() == "USD":
                selected = balance
                break
        if not selected and balances and isinstance(balances[0], Mapping):
            selected = balances[0]
        if not selected:
            raise ValueError("No account balance was returned.")
        current = float(selected.get("currentBalance") or 0.0)
        buying_power_raw = selected.get("buyingPower")
        buying_power = (
            current if buying_power_raw in (None, "") else float(buying_power_raw)
        )
        if current <= 0.0 or buying_power <= 0.0:
            raise ValueError("Account has no available USD buying power.")
        return current, buying_power

    def _stake_amount(self, account_balance: float, buying_power: float) -> float:
        requested = account_balance * (self.config.bankroll_pct / 100.0)
        available = min(requested, buying_power)
        return math.floor((available + 1e-9) * 100.0) / 100.0

    def _preview_order(self, order_request: Mapping[str, Any]) -> Mapping[str, Any]:
        # The SDK versions used by this project have exposed both a wrapped
        # {"request": ...} shape and a direct order-request shape. The wrapped
        # form is tried first because it is the shape already proven in the
        # deployed execution engine; the direct form preserves compatibility
        # with the current public SDK documentation.
        errors: list[str] = []
        for payload in ({"request": dict(order_request)}, dict(order_request)):
            try:
                result = self.client.orders.preview(payload)
                return result if isinstance(result, Mapping) else {}
            except Exception as exc:
                errors.append(str(exc))
        raise RuntimeError(
            "Polymarket order preview failed for both supported SDK payload "
            f"shapes: {' | '.join(errors)}"
        )

    @staticmethod
    def _order_id(response: Mapping[str, Any]) -> str:
        direct = str(response.get("id") or response.get("orderId") or "").strip()
        if direct:
            return direct
        nested = response.get("order")
        if isinstance(nested, Mapping):
            nested_id = str(nested.get("id") or nested.get("orderId") or "").strip()
            if nested_id:
                return nested_id
        for execution in response.get("executions") or []:
            if not isinstance(execution, Mapping):
                continue
            order = execution.get("order")
            if isinstance(order, Mapping):
                nested_id = str(order.get("id") or order.get("orderId") or "").strip()
                if nested_id:
                    return nested_id
        return ""

    def _verify_order_status(
        self, order_id: str, create_response: Mapping[str, Any]
    ) -> tuple[Mapping[str, Any], str]:
        initial_status, _state, _reason, _filled = self._interpret_order_response(
            create_response
        )
        if not order_id:
            return create_response, "Polymarket returned no order identifier."

        last_error = ""
        last_response: Mapping[str, Any] = create_response
        for attempt in range(3):
            try:
                retrieved = self.client.orders.retrieve(order_id) or {}
                if isinstance(retrieved, Mapping) and retrieved:
                    last_response = retrieved
                    status, _state, _reason, _filled = self._interpret_order_response(
                        retrieved
                    )
                    if status in {"EXECUTED", "REJECTED", "UNFILLED"}:
                        return retrieved, ""
            except Exception as exc:
                last_error = str(exc)
                break
            if attempt < 2:
                time.sleep(0.25 * (attempt + 1))

        # A definitive synchronous fill/reject is still authoritative if the
        # follow-up endpoint is briefly unavailable. A bare ID is never enough.
        if initial_status in {"EXECUTED", "REJECTED", "UNFILLED"}:
            return create_response, last_error
        return last_response, last_error

    @staticmethod
    def _interpret_order_response(
        response: Mapping[str, Any],
    ) -> tuple[str, str, str, float]:
        payloads: list[Mapping[str, Any]] = [response]
        nested_order = response.get("order")
        if isinstance(nested_order, Mapping):
            payloads.append(nested_order)

        executions = list(response.get("executions") or [])
        states: list[str] = []
        types: list[str] = []
        rejection_text: list[str] = []
        filled_quantities: list[float] = []

        def collect_order(order: Mapping[str, Any]) -> None:
            state = str(order.get("state") or order.get("status") or "").strip().upper()
            if state:
                states.append(state)
            for key in ("cumQuantity", "cumulativeQuantity", "filledQuantity", "cumQty"):
                value = order.get(key)
                try:
                    quantity = float(value)
                except (TypeError, ValueError):
                    continue
                if quantity > 0:
                    filled_quantities.append(quantity)
            for key in ("orderRejectReason", "rejectReason", "reason", "error", "message", "text"):
                text = str(order.get(key) or "").strip()
                if text:
                    rejection_text.append(text)

        for payload in payloads:
            collect_order(payload)

        for execution in executions:
            if not isinstance(execution, Mapping):
                continue
            execution_type = str(execution.get("type") or "").strip().upper()
            if execution_type:
                types.append(execution_type)
            order = execution.get("order")
            if isinstance(order, Mapping):
                collect_order(order)
            for key in ("lastShares", "lastQuantity", "filledQuantity"):
                value = execution.get(key)
                try:
                    quantity = float(value)
                except (TypeError, ValueError):
                    continue
                if quantity > 0:
                    filled_quantities.append(quantity)
            text = str(
                execution.get("orderRejectReason")
                or execution.get("rejectReason")
                or execution.get("text")
                or ""
            ).strip()
            if text:
                rejection_text.append(text)

        order_state = states[-1] if states else ""
        filled_quantity = max(filled_quantities, default=0.0)
        joined_states = " ".join(states)
        joined_types = " ".join(types)

        if "REJECT" in joined_types or "REJECT" in joined_states:
            return (
                "REJECTED",
                order_state,
                rejection_text[-1] if rejection_text else "Order was rejected.",
                filled_quantity,
            )
        if (
            "PARTIAL_FILL" in joined_types
            or "PARTIALLY_FILLED" in joined_states
            or (filled_quantity > 0 and "CANCEL" in joined_states)
        ):
            return (
                "EXECUTED",
                order_state,
                "Order partially filled; unfilled remainder was canceled.",
                filled_quantity,
            )
        if "FILL" in joined_types or "FILLED" in joined_states or filled_quantity > 0:
            return "EXECUTED", order_state, "Order fill confirmed.", filled_quantity
        if any(token in joined_states for token in ("CANCELED", "CANCELLED", "EXPIRED")):
            return (
                "UNFILLED",
                order_state,
                rejection_text[-1] if rejection_text else "Order ended without a fill.",
                0.0,
            )
        if any(token in joined_states for token in ("PENDING", "NEW", "OPEN", "ACCEPTED")):
            return (
                "PENDING",
                order_state,
                "Order submitted; final fill status is not yet confirmed.",
                0.0,
            )
        if PolymarketExecutionEngine._order_id(response):
            return (
                "PENDING",
                order_state,
                "Order ID returned; final fill status is not yet confirmed.",
                0.0,
            )
        return "FAILED", order_state, "Polymarket returned no verifiable order result.", 0.0

    @staticmethod
    def _price_string(value: float) -> str:
        return f"{value:.4f}".rstrip("0").rstrip(".")


def _last_name(value: str) -> str:
    tokens = _normalize(value).split()
    return tokens[-1] if tokens else ""


def _extract_market_mappings(payload: Any) -> list[Mapping[str, Any]]:
    """Recursively collect SDK search market objects without trusting layout."""
    found: list[Mapping[str, Any]] = []
    seen_ids: set[int] = set()

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            identity = id(value)
            if identity in seen_ids:
                return
            seen_ids.add(identity)
            if str(value.get("slug") or value.get("marketSlug") or "").strip() and any(
                key in value
                for key in ("marketSides", "sportsMarketType", "marketType", "question", "title", "active", "closed")
            ):
                found.append(value)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                walk(nested)

    walk(payload)
    return found


def _amount_value(value: Any) -> float | None:
    if isinstance(value, Mapping):
        value = value.get("value")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0.0 < number < 1.0 else None


def _market_payload(payload: Any) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    nested = payload.get("market")
    if isinstance(nested, Mapping) and nested:
        return nested
    return payload


def _market_data(payload: Any) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        return {}
    nested = payload.get("marketData")
    if isinstance(nested, Mapping):
        return nested
    # Keep compatibility with earlier SDK/test fixtures while treating the
    # documented marketData object as authoritative when it is present.
    return payload


def _normalize(value: str) -> str:
    ascii_text = (
        unicodedata.normalize("NFKD", value or "")
        .encode("ascii", "ignore")
        .decode()
    )
    return " ".join(re.sub(r"[^a-zA-Z0-9 ]+", " ", ascii_text).lower().split())


def _team_names(side: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
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
            "description",
            "identifier",
            "outcome",
            "label",
        ):
            value = str(source.get(key) or "").strip()
            normalized = _normalize(value)
            if value and normalized not in {_normalize(item) for item in names}:
                names.append(value)
    return names


def _coerce_long_flag(side: Mapping[str, Any]) -> bool | None:
    value = side.get("long")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in {0, 1}:
        return bool(value)
    normalized = _normalize(str(value or ""))
    if normalized in {"true", "yes", "long", "buy long"}:
        return True
    if normalized in {"false", "no", "short", "buy short"}:
        return False

    for key in ("side", "position", "contractSide", "outcomeType", "outcome"):
        normalized = _normalize(str(side.get(key) or ""))
        if normalized in {"long", "yes", "affirmative"}:
            return True
        if normalized in {"short", "no", "negative"}:
            return False
    return None


def _structured_market_sides(market: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_sides = (
        market.get("marketSides")
        or market.get("sides")
        or market.get("outcomes")
        or []
    )
    if not isinstance(raw_sides, list):
        return []
    sides: list[dict[str, Any]] = []
    for raw_side in raw_sides:
        if not isinstance(raw_side, Mapping):
            continue
        long_flag = _coerce_long_flag(raw_side)
        names = _team_names(raw_side)
        if long_flag is None or not names:
            continue
        sides.append({"long": long_flag, "names": names})
    # A binary market must expose one LONG and one SHORT contract. Reject
    # malformed or duplicate side metadata rather than guessing.
    if len(sides) != 2 or {side["long"] for side in sides} != {True, False}:
        return []
    return sides


def _name_match_score(expected: str, candidate: str) -> float:
    """Match abbreviated API Tennis names to authenticated market-side names.

    Middle initials are optional identity evidence, not surname components.
    V6.5.7 incorrectly treated the ``H.`` in ``M. H. Rehberg`` as part of the
    surname and therefore failed to map it to ``Max Hans Rehberg``.
    """
    left = _normalize(expected)
    right = _normalize(candidate)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0

    left_tokens = left.split()
    right_tokens = right.split()

    # A surname-only feed value can be used only as a lower-confidence exact
    # token match. The assignment layer still requires the opponent to map
    # uniquely to the other contract, preventing ambiguous same-surname trades.
    if len(left_tokens) == 1:
        return 0.95 if left_tokens[0] in right_tokens else 0.0
    if len(right_tokens) == 1:
        return 0.95 if right_tokens[0] in left_tokens else 0.0

    expected_surname = left_tokens[-1]
    if expected_surname not in right_tokens:
        return 0.0

    expected_first = left_tokens[0]
    candidate_given = [token for token in right_tokens if token != expected_surname]
    if not candidate_given:
        return 0.95
    if expected_first in candidate_given:
        base = 0.99
    elif any(expected_first[:1] == token[:1] for token in candidate_given):
        base = 0.97
    else:
        return 0.0

    expected_middle = left_tokens[1:-1]
    if expected_middle:
        middle_hits = sum(
            1
            for token in expected_middle
            if any(token == other or token[:1] == other[:1] for other in candidate_given)
        )
        if middle_hits == len(expected_middle):
            return min(1.0, base + 0.02)
    return base


def _unique_best_side(
    expected: str, sides: list[dict[str, Any]], *, minimum_score: float = 0.94
) -> int | None:
    scores = [
        max((_name_match_score(expected, name) for name in side["names"]), default=0.0)
        for side in sides
    ]
    if not scores:
        return None
    best = max(scores)
    if best < minimum_score:
        return None
    winners = [index for index, score in enumerate(scores) if abs(score - best) < 1e-9]
    return winners[0] if len(winners) == 1 else None


def _structured_side_assignment(
    market: Mapping[str, Any], player: str, opponent: str
) -> tuple[int, int, list[dict[str, Any]]] | None:
    sides = _structured_market_sides(market)
    if len(sides) < 2:
        return None
    player_index = _unique_best_side(player, sides)
    opponent_index = _unique_best_side(opponent, sides)
    if player_index is None or opponent_index is None or player_index == opponent_index:
        return None
    if sides[player_index]["long"] == sides[opponent_index]["long"]:
        return None
    return player_index, opponent_index, sides


def _surname_matches(name: str, haystack: str) -> bool:
    tokens = _normalize(name).split()
    if len(tokens) < 2:
        return False
    haystack_tokens = set(_normalize(haystack).split())
    # Ignore one-letter middle initials such as the H in M. H. Rehberg while
    # preserving real compound surnames such as Pascual Ferra.
    surname_tokens = [token for token in tokens[1:] if len(token) >= 3]
    return bool(surname_tokens) and all(
        token in haystack_tokens for token in surname_tokens
    )
