"""Small, strict Polymarket US executor for approved tennis trade signals.

The scanner decides *whether* to trade.  This module does only five things:

1. Resolve the exact Polymarket sports event for the two players.
2. Select the event's match-winner moneyline using structured API fields.
3. Map the backed player to LONG/YES or SHORT/NO.
4. Size and preview one bounded-slippage market order from authenticated buying power.
5. Confirm the exchange order state and report it without guessing.

No fuzzy market-wide candidate harvesting is used.  Public discovery can suggest
an event, but the authenticated market payload is the final authority.
"""

from __future__ import annotations

import re
import time
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from typing import Any, Protocol

OPEN_MARKET_STATES = {"MARKET_STATE_OPEN", "OPEN"}
LONG_SIDE = "Long / YES"
SHORT_SIDE = "Short / NO"
YES_OUTCOME_SIDE = "OUTCOME_SIDE_YES"
NO_OUTCOME_SIDE = "OUTCOME_SIDE_NO"
BUY_ACTION = "ORDER_ACTION_BUY"
BUY_LONG_INTENT = "ORDER_INTENT_BUY_LONG"
BUY_SHORT_INTENT = "ORDER_INTENT_BUY_SHORT"
BUY_INTENT_TO_OUTCOME = {
    BUY_LONG_INTENT: YES_OUTCOME_SIDE,
    BUY_SHORT_INTENT: NO_OUTCOME_SIDE,
}
MONEYLINE_TYPES = {
    "SPORTS_MARKET_TYPE_MONEYLINE",
    "MONEYLINE",
    "MATCH_WINNER",
    "MATCH WINNER",
}
NON_MONEYLINE_PATTERNS = (
    r"\bSPREAD\b",
    r"\bHANDICAP\b",
    r"\bTOTALS?\b",
    r"\bCOVER(?:S|ED)?\b",
    r"\bEXACT(?: SET)? SCORE\b",
    r"\bSET SCORE\b",
    r"\bWIN(?:S|NER)? (?:THE )?(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|[1-5](?:ST|ND|RD|TH)) SET\b",
    r"\bSET [1-5]\b",
    r"\bGAME [0-9]+\b",
    r"\bOVER [0-9]",
    r"\bUNDER [0-9]",
    r"\bMARGIN(?: OF VICTORY)?\b",
    r"\bFIRST TO\b",
    r"\bRACE TO\b",
    r"\b(?:WIN|WINS|SCORE|RESULT)[^\n]{0,24}\b(?:2[- ]0|0[- ]2|3[- ]0|0[- ]3)\b",
    r"\bSTRAIGHT SETS?\b",
    r"\bCORRECT (?:MATCH |SET )?SCORE\b",
    r"\bMATCH SCORE\b",
    r"\bSET BETTING\b",
    r"\bFIRST SET WINNER\b",
    r"\bTIE[ -]?BREAK\b",
    r"\bNUMBER OF SETS\b",
    r"\bWINS? (?:THE MATCH )?(?:2|3) SETS? TO (?:0|1)\b",
)
TERMINAL_ORDER_STATES = {
    "ORDER_STATE_FILLED",
    "ORDER_STATE_CANCELED",
    "ORDER_STATE_REJECTED",
    "ORDER_STATE_EXPIRED",
}
DEFAULT_EXCHANGE_REJECT_REASON = "ORD_REJECT_REASON_EXCHANGE_OPTION"

PENDING_ORDER_STATES = {
    "ORDER_STATE_NEW",
    "ORDER_STATE_PENDING_NEW",
    "ORDER_STATE_PENDING_REPLACE",
    "ORDER_STATE_PENDING_CANCEL",
    "ORDER_STATE_PENDING_RISK",
}


class ExecutionClient(Protocol):
    account: Any
    events: Any
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
    slippage_ticks: int = 3
    event_page_size: int = 100
    event_page_limit: int = 8
    order_status_attempts: int = 6
    api_read_attempts: int = 3
    api_min_interval_seconds: float = 0.20
    rate_limit_backoff_seconds: float = 1.0
    # Retained only so existing Railway environment/configuration remains
    # compatible.  The new executor never uses a public confidence threshold.
    minimum_market_confidence: float = 0.0


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
    event_id: str = ""
    game_id: str = ""
    minimum_trade_qty: float = 0.0
    tick_size: float = 0.0
    order_type: str = ""
    order_quantity: float = 0.0
    yes_reference_price_cents: float = 0.0
    maximum_player_price_cents: float = 0.0
    best_yes_bid_cents: float = 0.0
    best_yes_offer_cents: float = 0.0
    slippage_ticks: int = 0
    retryable: bool = False
    failure_stage: str = ""

    @property
    def order_created(self) -> bool:
        return self.status == "EXECUTED"

    @property
    def terminal(self) -> bool:
        # A pending exchange order ID is an idempotency boundary: never submit
        # another order while its final state is unknown.  A *known* rejected
        # or zero-fill IOC order may be retried only when explicitly classified
        # as retryable, because the exchange confirmed it did not fill.
        if self.status == "PENDING" and self.order_id:
            return True
        if self.status == "EXECUTED":
            return True
        return not self.retryable and self.status in {"REJECTED", "UNFILLED", "PENDING"}

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
            "event_id": self.event_id,
            "game_id": self.game_id,
            "minimum_trade_qty": self.minimum_trade_qty,
            "tick_size": self.tick_size,
            "order_type": self.order_type,
            "order_quantity": self.order_quantity,
            "yes_reference_price_cents": self.yes_reference_price_cents,
            "maximum_player_price_cents": self.maximum_player_price_cents,
            "best_yes_bid_cents": self.best_yes_bid_cents,
            "best_yes_offer_cents": self.best_yes_offer_cents,
            "slippage_ticks": self.slippage_ticks,
            "retryable": self.retryable,
            "failure_stage": self.failure_stage,
        }


@dataclass(frozen=True)
class ResolvedMarket:
    event: Mapping[str, Any]
    market: Mapping[str, Any]
    market_slug: str
    market_side: str
    event_id: str
    game_id: str


class PolymarketExecutionEngine:
    """Strict event-first execution engine.

    Different matches can be held simultaneously.  A second order on the same
    market is blocked when the exchange reports an open order, decimal position,
    or prior trade execution.  Those checks reduce restart duplicate risk without
    relying on Railway's local filesystem, but they are not a perfect client-side
    idempotency key during exchange eventual-consistency windows.
    """

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
            from polymarket_us import PolymarketUS

            self.client = PolymarketUS(
                key_id=config.key_id,
                secret_key=config.secret_key,
                timeout=20.0,
            )
        self._next_api_call_at = 0.0

    def close(self) -> None:
        self.client.close()

    def _wait_for_api_slot(self) -> None:
        """Space authenticated SDK calls so one worker does not burst at the edge."""

        interval = max(0.0, float(self.config.api_min_interval_seconds))
        now = time.monotonic()
        if now < self._next_api_call_at:
            time.sleep(self._next_api_call_at - now)
        self._next_api_call_at = time.monotonic() + interval

    def _rate_limit_delay(self, attempt: int) -> None:
        delay = max(0.0, float(self.config.rate_limit_backoff_seconds)) * (2**attempt)
        if delay:
            time.sleep(delay)

    def _read_api(self, call: Any, *, stage: str, label: str) -> Any:
        last_error: Exception | None = None
        attempts = max(1, int(self.config.api_read_attempts))
        for attempt in range(attempts):
            try:
                self._wait_for_api_slot()
                return call()
            except Exception as exc:  # SDK exceptions share status_code/request_id fields.
                last_error = exc
                if _is_edge_rate_limit(exc):
                    if attempt + 1 < attempts:
                        self._rate_limit_delay(attempt)
                        continue
                    break
                if _is_definitive_api_rejection(exc):
                    raise PermanentAPIExecutionError(
                        f"{label} was rejected by Polymarket: {_safe_exception_message(exc)}",
                        stage,
                        status_code=_exception_status_code(exc),
                    ) from exc
                if attempt + 1 < attempts:
                    time.sleep(min(0.5, 0.1 * (2**attempt)))
        message = _safe_exception_message(last_error) if last_error is not None else "unknown error"
        raise RetryableExecutionError(f"{label} failed: {message}", stage) from last_error

    def _create_order(self, order_request: Mapping[str, Any]) -> Mapping[str, Any]:
        """Retry only definite edge throttles; never replay an ambiguous POST."""

        attempts = max(1, int(self.config.api_read_attempts))
        for attempt in range(attempts):
            try:
                self._wait_for_api_slot()
                payload = self.client.orders.create(dict(order_request)) or {}
                return payload if isinstance(payload, Mapping) else {}
            except Exception as exc:
                if not _is_edge_rate_limit(exc):
                    raise
                if attempt + 1 < attempts:
                    self._rate_limit_delay(attempt)
                    continue
                raise RetryableExecutionError(
                    "Polymarket/Cloudflare temporarily rate-limited the order request (1015/429).",
                    "order_submission",
                ) from exc
        raise RetryableExecutionError(
            "Polymarket/Cloudflare temporarily rate-limited the order request (1015/429).",
            "order_submission",
        )

    @staticmethod
    def signal_key(record: Mapping[str, Any]) -> str:
        event_key = str(record.get("trade_key") or record.get("event_key") or "").strip()
        player = _normalize_name(str(record.get("player") or ""))
        return f"{event_key}|{player}" if event_key else player

    def execute_trade(self, record: Mapping[str, Any]) -> ExecutionResult:
        player = str(record.get("player") or "").strip()
        opponent = str(record.get("opponent") or "").strip()
        signal_key = self.signal_key(record)
        change = str(record.get("recommendation_change") or "INITIAL").strip().upper()

        base = {
            "signal_key": signal_key,
            "player": player,
            "opponent": opponent,
            "bankroll_pct": self.config.bankroll_pct,
            "recommendation_change": change,
        }

        def result(status: str, reason: str, **fields: Any) -> ExecutionResult:
            return ExecutionResult(status=status, reason=reason, **base, **fields)

        if record.get("decision_status") != "TRADE":
            return result("REJECTED", "Scanner record is not an approved TRADE.", failure_stage="input")
        if not record.get("alert_eligible"):
            return result("REJECTED", "Scanner record is not eligible for a new trade alert.", failure_stage="input")
        if not player or not opponent or _normalize_name(player) == _normalize_name(opponent):
            return result("REJECTED", "Scanner signal does not contain two different players.", failure_stage="input")

        try:
            resolved = self._resolve_market(record, player, opponent)
        except RetryableExecutionError as exc:
            return result("FAILED", str(exc), retryable=True, failure_stage=exc.stage)
        except PermanentExecutionError as exc:
            return result("REJECTED", str(exc), retryable=False, failure_stage=exc.stage)
        except Exception as exc:
            return result(
                "FAILED",
                f"Unexpected market resolution failure: {_safe_exception_message(exc)}",
                retryable=True,
                failure_stage="market_resolution",
            )

        market = resolved.market
        slug = resolved.market_slug
        question = _market_question(market)
        market_type = _market_type(market)
        common = {
            "market_slug": slug,
            "market_side": resolved.market_side,
            "market_question": question,
            "market_type": market_type,
            "event_id": resolved.event_id,
            "game_id": resolved.game_id,
        }

        execution_trace: dict[str, Any] = {}
        try:
            open_orders = self._read_api(
                lambda: self._open_orders(slug),
                stage="idempotency",
                label=f"Polymarket open-order lookup for {slug}",
            )
            existing_order = _find_exposure_order(open_orders, slug)
            if existing_order is not None:
                prior_status, prior_state, _prior_reason, prior_filled = _interpret_order(existing_order)
                if prior_status == "EXECUTED":
                    return result(
                        "REJECTED",
                        "A filled order already exists for this exact Polymarket market; duplicate exposure was blocked.",
                        retryable=False,
                        failure_stage="idempotency",
                        order_id=_order_id(existing_order),
                        order_state=prior_state,
                        filled_quantity=prior_filled,
                        **common,
                    )
                return result(
                    "PENDING",
                    "An order for this exact Polymarket market is already pending; no duplicate was submitted.",
                    retryable=False,
                    failure_stage="idempotency",
                    order_id=_order_id(existing_order),
                    order_state=prior_state,
                    **common,
                )

            positions = self._read_api(
                lambda: self._positions(slug),
                stage="idempotency",
                label=f"Polymarket position lookup for {slug}",
            )
            if _has_position(positions, slug):
                return result(
                    "REJECTED",
                    "A position for this exact Polymarket market already exists; a second 20% order was blocked.",
                    retryable=False,
                    failure_stage="idempotency",
                    **common,
                )

            activities = self._read_api(
                lambda: self._activities(slug),
                stage="idempotency",
                label=f"Polymarket trade-activity lookup for {slug}",
            )
            prior_trade = _find_trade_activity(activities, slug)
            if prior_trade is not None:
                return result(
                    "REJECTED",
                    "A prior trade execution already exists for this exact Polymarket market; duplicate exposure was blocked.",
                    retryable=False,
                    failure_stage="idempotency",
                    filled_quantity=float(_trade_quantity(prior_trade) or Decimal("0")),
                    **common,
                )

            book = _unwrap_book(
                self._read_api(
                    lambda: self.client.markets.book(slug),
                    stage="order_book",
                    label=f"Polymarket order book retrieval for {slug}",
                )
                or {}
            )
            if not book:
                raise RetryableExecutionError("Polymarket returned no usable order book.", "order_book")
            state = str(book.get("state") or "").strip().upper()
            if state not in OPEN_MARKET_STATES:
                raise RetryableExecutionError(
                    f"Polymarket order book is not open (state: {state or 'missing'}).",
                    "order_book",
                )

            best_yes_bid, best_yes_offer = _best_yes_prices(book)
            long_reference, player_price = _execution_prices(book, resolved.market_side)
            player_price_cents = round(float(player_price * Decimal("100")), 2)
            if not self.config.minimum_price_cents <= player_price_cents <= self.config.maximum_price_cents:
                return result(
                    "REJECTED",
                    "Live player price is outside the configured execution range.",
                    retryable=True,
                    failure_stage="price",
                    player_price_cents=player_price_cents,
                    **common,
                )

            minimum_qty = _required_decimal(market, "minimumTradeQty")
            tick_size = _required_decimal(market, "orderPriceMinTickSize")
            if minimum_qty <= 0 or tick_size <= 0:
                raise PermanentExecutionError(
                    "Authenticated market is missing valid minimumTradeQty or orderPriceMinTickSize.",
                    "market_metadata",
                )

            balance, buying_power = _usd_balance(
                self._read_api(
                    self.client.account.balances,
                    stage="sizing",
                    label="Polymarket account balance retrieval",
                )
                or {}
            )
            stake = _stake_amount(balance, buying_power, self.config.bankroll_pct)
            if stake < Decimal(str(self.config.minimum_order_usd)):
                return result(
                    "REJECTED",
                    f"Calculated {self.config.bankroll_pct:g}% stake is below the minimum live order.",
                    retryable=True,
                    failure_stage="sizing",
                    account_balance=float(balance),
                    buying_power=float(buying_power),
                    stake_amount=float(stake),
                    player_price_cents=player_price_cents,
                    minimum_trade_qty=float(minimum_qty),
                    tick_size=float(tick_size),
                    **common,
                )

            # Market orders are the exchange-native taker path for both outcomes.
            # The previous SHORT implementation used an undocumented cashOrderQty
            # market request, then a synthetic IOC limit.  The official create
            # contract instead requires quantity for market orders.  Quantity is
            # sized at the worst permitted backed-outcome price so the order cannot
            # spend more than the configured bankroll stake when slippage is honored.
            slippage_ticks = max(0, int(self.config.slippage_ticks))
            adverse_player_price = min(
                Decimal("0.99"),
                player_price + tick_size * Decimal(slippage_ticks),
            )
            estimated_quantity = _quantity_for_stake(stake, adverse_player_price, minimum_qty)
            if estimated_quantity < minimum_qty:
                return result(
                    "REJECTED",
                    "The 20% stake cannot meet this market's minimum trade quantity.",
                    retryable=True,
                    failure_stage="sizing",
                    account_balance=float(balance),
                    buying_power=float(buying_power),
                    stake_amount=float(stake),
                    player_price_cents=player_price_cents,
                    minimum_trade_qty=float(minimum_qty),
                    tick_size=float(tick_size),
                    **common,
                )

            long_reference = _align_price(long_reference, tick_size)
            expected_outcome_side = (
                YES_OUTCOME_SIDE if resolved.market_side == LONG_SIDE else NO_OUTCOME_SIDE
            )
            expected_intent = (
                BUY_LONG_INTENT if resolved.market_side == LONG_SIDE else BUY_SHORT_INTENT
            )
            order_request = {
                "marketSlug": slug,
                # Send both supported representations. Polymarket documents that
                # outcomeSide + action takes priority when both are present, so
                # SHORT/NO cannot be interpreted as a legacy LONG/YES request.
                "intent": expected_intent,
                "outcomeSide": expected_outcome_side,
                "action": BUY_ACTION,
                "type": "ORDER_TYPE_MARKET",
                "quantity": float(estimated_quantity),
                "tif": "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
                "manualOrderIndicator": "MANUAL_ORDER_INDICATOR_AUTOMATIC",
                "synchronousExecution": True,
                "maxBlockTime": "5",
                "slippageTolerance": {
                    # Polymarket requires the YES/long reference price even when
                    # outcomeSide is NO. The intent tells the exchange which
                    # direction is adverse for the configured tick tolerance.
                    "currentPrice": {
                        "value": _decimal_string(long_reference),
                        "currency": "USD",
                    },
                    "ticks": slippage_ticks,
                },
            }
            execution_trace = {
                "order_type": "ORDER_TYPE_MARKET",
                "order_quantity": float(estimated_quantity),
                "yes_reference_price_cents": round(float(long_reference * Decimal("100")), 2),
                "maximum_player_price_cents": round(float(adverse_player_price * Decimal("100")), 2),
                "best_yes_bid_cents": round(float(best_yes_bid * Decimal("100")), 2),
                "best_yes_offer_cents": round(float(best_yes_offer * Decimal("100")), 2),
                "slippage_ticks": slippage_ticks,
            }

            preview = self._preview(order_request)
            preview_order = preview.get("order") if isinstance(preview, Mapping) else None
            if not isinstance(preview_order, Mapping):
                raise RetryableExecutionError(
                    "Polymarket preview returned no order object; live submission was blocked.",
                    "preview",
                )
            preview_slug = str(preview_order.get("marketSlug") or "").strip()
            if preview_slug and preview_slug.casefold() != slug.casefold():
                raise PermanentExecutionError(
                    f"Polymarket preview returned the wrong market slug: {preview_slug}",
                    "preview",
                )
            _validate_order_payload_contract(
                preview,
                expected_slug=slug,
                expected_outcome_side=expected_outcome_side,
                stage="preview",
            )
            preview_status, preview_state, preview_reason, _ = _interpret_order(preview)
            if preview_status == "REJECTED":
                return result(
                    "REJECTED",
                    f"Polymarket preview rejected the order: {preview_reason}",
                    retryable=_retryable_order_outcome(
                        preview_status, preview_state, preview_reason, 0.0
                    ),
                    failure_stage="preview",
                    account_balance=float(balance),
                    buying_power=float(buying_power),
                    stake_amount=float(stake),
                    player_price_cents=player_price_cents,
                    order_state=preview_state,
                    minimum_trade_qty=float(minimum_qty),
                    tick_size=float(tick_size),
                    **execution_trace,
                    **common,
                )

            try:
                created = self._create_order(order_request)
            except RetryableExecutionError as create_error:
                return result(
                    "FAILED",
                    str(create_error),
                    retryable=True,
                    failure_stage=create_error.stage,
                    account_balance=float(balance),
                    buying_power=float(buying_power),
                    stake_amount=float(stake),
                    player_price_cents=player_price_cents,
                    minimum_trade_qty=float(minimum_qty),
                    tick_size=float(tick_size),
                    **execution_trace,
                    **common,
                )
            except Exception as create_error:
                if _is_definitive_api_rejection(create_error):
                    return result(
                        "REJECTED",
                        f"Polymarket rejected the order request before accepting it: {_safe_exception_message(create_error)}",
                        retryable=False,
                        failure_stage="order_submission",
                        account_balance=float(balance),
                        buying_power=float(buying_power),
                        stake_amount=float(stake),
                        player_price_cents=player_price_cents,
                        minimum_trade_qty=float(minimum_qty),
                        tick_size=float(tick_size),
                        **execution_trace,
                        **common,
                    )

                # A timeout/connection loss can happen after the exchange accepted
                # the order. Reconcile the exact market, but never auto-retry an
                # ambiguous POST: an eventually consistent order/position could
                # appear after these reads complete.
                reconciliation_errors: list[str] = []
                recovered_order = None
                try:
                    recovered_order = _find_exposure_order(
                        self._read_api(
                            lambda: self._open_orders(slug),
                            stage="order_submission",
                            label=f"Post-submit exact-order reconciliation for {slug}",
                        ),
                        slug,
                    )
                except ExecutionError as exc:
                    reconciliation_errors.append(str(exc))
                if recovered_order is not None:
                    recovered_status, recovered_state, recovered_reason, recovered_filled = _interpret_order(
                        recovered_order
                    )
                    return result(
                        recovered_status if recovered_status == "EXECUTED" else "PENDING",
                        (
                            recovered_reason
                            if recovered_status == "EXECUTED"
                            else "Order submission response was interrupted, but a pending order was found for this market."
                        ),
                        retryable=False,
                        failure_stage="order_submission",
                        order_id=_order_id(recovered_order),
                        order_state=recovered_state,
                        filled_quantity=recovered_filled,
                        account_balance=float(balance),
                        buying_power=float(buying_power),
                        stake_amount=float(stake),
                        player_price_cents=player_price_cents,
                        minimum_trade_qty=float(minimum_qty),
                        tick_size=float(tick_size),
                        **execution_trace,
                        **common,
                    )

                recovered_position = False
                try:
                    recovered_position = _has_position(
                        self._read_api(
                            lambda: self._positions(slug),
                            stage="order_submission",
                            label=f"Post-submit position reconciliation for {slug}",
                        ),
                        slug,
                    )
                except ExecutionError as exc:
                    reconciliation_errors.append(str(exc))
                if recovered_position:
                    return result(
                        "PENDING",
                        "Order submission response was interrupted, but a position appeared for this market.",
                        retryable=False,
                        failure_stage="order_submission",
                        account_balance=float(balance),
                        buying_power=float(buying_power),
                        stake_amount=float(stake),
                        player_price_cents=player_price_cents,
                        minimum_trade_qty=float(minimum_qty),
                        tick_size=float(tick_size),
                        **execution_trace,
                        **common,
                    )

                recovered_trade = None
                try:
                    recovered_trade = _find_trade_activity(
                        self._read_api(
                            lambda: self._activities(slug),
                            stage="order_submission",
                            label=f"Post-submit trade-activity reconciliation for {slug}",
                        ),
                        slug,
                    )
                except ExecutionError as exc:
                    reconciliation_errors.append(str(exc))
                if recovered_trade is not None:
                    recovered_qty = _trade_quantity(recovered_trade) or Decimal("0")
                    return result(
                        "EXECUTED",
                        "Order submission response was interrupted, but an exact-market trade execution was found.",
                        retryable=False,
                        failure_stage="order_submission",
                        filled_quantity=float(recovered_qty),
                        account_balance=float(balance),
                        buying_power=float(buying_power),
                        stake_amount=float(stake),
                        player_price_cents=player_price_cents,
                        minimum_trade_qty=float(minimum_qty),
                        tick_size=float(tick_size),
                        **execution_trace,
                        **common,
                    )

                reconciliation_note = (
                    " Reconciliation errors: " + "; ".join(reconciliation_errors[-2:])
                    if reconciliation_errors
                    else " No open order or position was visible immediately after the interruption."
                )
                return result(
                    "PENDING",
                    "Polymarket order submission outcome is unknown, so automatic retry was suppressed "
                    "to prevent a duplicate order." + reconciliation_note,
                    retryable=False,
                    failure_stage="order_submission",
                    account_balance=float(balance),
                    buying_power=float(buying_power),
                    stake_amount=float(stake),
                    player_price_cents=player_price_cents,
                    minimum_trade_qty=float(minimum_qty),
                    tick_size=float(tick_size),
                    **execution_trace,
                    **common,
                )

            _validate_order_payload_contract(
                created,
                expected_slug=slug,
                expected_outcome_side=expected_outcome_side,
                stage="order_submission",
            )
            order_id = _order_id(created)
            verified = self._confirm_order(order_id, created)
            _validate_order_payload_contract(
                verified,
                expected_slug=slug,
                expected_outcome_side=expected_outcome_side,
                stage="order_status",
            )
            status, order_state, reason, filled = _interpret_order(verified)
            status_poll_error = str(verified.get("_status_poll_error") or "").strip()
            if status == "PENDING" and status_poll_error:
                reason = (
                    "Order submission returned an ID, but final-state polling failed; "
                    f"automatic resubmission is blocked: {status_poll_error}"
                )
            # Pending/unknown orders with an ID are never retried.  Known
            # zero-fill IOC cancellations and transient exchange rejections can
            # be retried from a fresh scanner snapshot because Polymarket has
            # already confirmed that no position was created.
            retryable = (status == "FAILED" and not order_id) or _retryable_order_outcome(
                status, order_state, reason, filled
            )
            return result(
                status,
                reason,
                retryable=retryable,
                failure_stage="order_status" if retryable else "",
                account_balance=float(balance),
                buying_power=float(buying_power),
                stake_amount=float(stake),
                player_price_cents=player_price_cents,
                order_id=order_id,
                order_state=order_state,
                filled_quantity=filled,
                minimum_trade_qty=float(minimum_qty),
                tick_size=float(tick_size),
                **execution_trace,
                **common,
            )
        except RetryableExecutionError as exc:
            return result(
                "FAILED",
                str(exc),
                retryable=True,
                failure_stage=exc.stage,
                **execution_trace,
                **common,
            )
        except PermanentExecutionError as exc:
            return result(
                "REJECTED",
                str(exc),
                retryable=False,
                failure_stage=exc.stage,
                **execution_trace,
                **common,
            )
        except Exception as exc:
            return result(
                "FAILED",
                f"Polymarket API request failed: {_safe_exception_message(exc)}",
                retryable=True,
                failure_stage="api",
                **execution_trace,
                **common,
            )

    def _resolve_market(
        self,
        record: Mapping[str, Any],
        player: str,
        opponent: str,
    ) -> ResolvedMarket:
        validation_errors: list[str] = []
        resolution_record = dict(record)
        direct_slug = str(record.get("market_slug") or "").strip()
        if direct_slug:
            try:
                market = _unwrap_market(
                    self._read_api(
                        lambda: self.client.markets.retrieve_by_slug(direct_slug),
                        stage="market_resolution",
                        label=f"Polymarket market retrieval for {direct_slug}",
                    )
                    or {}
                )
                event_slug = str(market.get("eventSlug") or "").strip()
                game_id = market.get("gameId")
                if event_slug:
                    resolution_record.setdefault("polymarket_event_slug", event_slug)
                if game_id not in (None, ""):
                    resolution_record.setdefault("polymarket_game_id", game_id)
                side = _validated_market_side(market, player, opponent)
                event = {"id": "", "gameId": game_id or "", "slug": event_slug}
                return ResolvedMarket(
                    event=event,
                    market=market,
                    market_slug=direct_slug,
                    market_side=side,
                    event_id="",
                    game_id=str(market.get("gameId") or ""),
                )
            except PermanentAPIExecutionError as exc:
                # A missing/bad scanner hint may fall back to event discovery,
                # but authentication and permission failures must never be
                # disguised as a market miss.
                if exc.status_code in {401, 403, 405}:
                    raise
                validation_errors.append(f"scanner_slug:{exc}")
            except ExecutionError as exc:
                validation_errors.append(f"scanner_slug:{exc}")
            except Exception as exc:
                validation_errors.append(f"scanner_slug_retrieve:{exc}")

        events = self._matching_events(resolution_record, player, opponent)
        if not events:
            detail = "; ".join(validation_errors[-3:])
            suffix = f" ({detail})" if detail else ""
            raise RetryableExecutionError(
                f"No active Polymarket tennis event matched both players{suffix}.",
                "event_discovery",
            )

        event = self._choose_event(events, record, player, opponent)
        markets = self._event_markets(event)
        valid: list[tuple[int, Mapping[str, Any], str]] = []
        rejected: list[str] = []
        for candidate in markets:
            slug = str(candidate.get("slug") or "").strip()
            if not slug:
                continue
            try:
                full = _unwrap_market(
                    self._read_api(
                        lambda slug=slug: self.client.markets.retrieve_by_slug(slug),
                        stage="market_selection",
                        label=f"Polymarket market retrieval for {slug}",
                    )
                    or {}
                )
                side = _validated_market_side(full, player, opponent)
                score = 100 if _explicit_moneyline(full) else 80
                valid.append((score, full, side))
            except PermanentAPIExecutionError as exc:
                # Authentication/permission errors are infrastructure failures,
                # not evidence that this event lacks a moneyline.  Surface them
                # immediately instead of walking the remaining candidates and
                # eventually misreporting a generic market-selection miss.
                if exc.status_code in {401, 403, 405}:
                    raise
                rejected.append(f"{slug}:{exc}")
            except ExecutionError as exc:
                rejected.append(f"{slug}:{exc}")
            except Exception as exc:
                rejected.append(f"{slug}:retrieve_failed:{exc}")

        if not valid:
            sample = "; ".join(rejected[:5])
            raise RetryableExecutionError(
                "The exact Polymarket event was found, but it contained no active match-winner moneyline "
                f"that mapped both players. Checked {len(markets)} event markets. {sample}",
                "market_selection",
            )

        valid.sort(key=lambda item: item[0], reverse=True)
        best_score = valid[0][0]
        best = [item for item in valid if item[0] == best_score]
        unique_slugs = {str(item[1].get("slug") or "") for item in best}
        if len(unique_slugs) != 1:
            raise PermanentExecutionError(
                f"Multiple equally valid moneyline markets were found for one event: {sorted(unique_slugs)}",
                "market_selection",
            )

        _score, market, side = best[0]
        return ResolvedMarket(
            event=event,
            market=market,
            market_slug=str(market.get("slug") or ""),
            market_side=side,
            event_id=str(event.get("id") or event.get("eventId") or ""),
            game_id=str(event.get("gameId") or market.get("gameId") or ""),
        )

    def _matching_events(
        self,
        record: Mapping[str, Any],
        player: str,
        opponent: str,
    ) -> list[Mapping[str, Any]]:
        metadata = record.get("market_metadata")
        metadata = metadata if isinstance(metadata, Mapping) else {}
        hinted_slug = str(
            record.get("polymarket_event_slug")
            or record.get("event_slug")
            or metadata.get("event_slug")
            or ""
        ).strip()
        hinted_game_id = (
            record.get("polymarket_game_id")
            or record.get("game_id")
            or metadata.get("game_id")
        )
        hinted_event_id = metadata.get("event_id") or record.get("polymarket_event_id")

        direct_events: list[Mapping[str, Any]] = []
        direct_errors: list[str] = []
        if hinted_slug and hasattr(self.client.events, "retrieve_by_slug"):
            try:
                payload = self._read_api(
                    lambda: self.client.events.retrieve_by_slug(hinted_slug),
                    stage="event_discovery",
                    label=f"Polymarket event retrieval for {hinted_slug}",
                ) or {}
                event = payload.get("event") if isinstance(payload, Mapping) else None
                if isinstance(event, Mapping) and _event_matches(event, player, opponent):
                    direct_events.append(event)
            except PermanentAPIExecutionError as exc:
                if exc.status_code not in {400, 404, 422}:
                    raise
                direct_errors.append(str(exc))
            except RetryableExecutionError as exc:
                direct_errors.append(str(exc))
        if hinted_event_id not in (None, "") and hasattr(self.client.events, "retrieve"):
            try:
                event_id = int(hinted_event_id)
                payload = self._read_api(
                    lambda: self.client.events.retrieve(event_id),
                    stage="event_discovery",
                    label=f"Polymarket event retrieval for id {event_id}",
                ) or {}
                event = payload.get("event") if isinstance(payload, Mapping) else None
                if isinstance(event, Mapping) and _event_matches(event, player, opponent):
                    direct_events.append(event)
            except (TypeError, ValueError) as exc:
                direct_errors.append(str(exc))
            except PermanentAPIExecutionError as exc:
                if exc.status_code not in {400, 404, 422}:
                    raise
                direct_errors.append(str(exc))
            except RetryableExecutionError as exc:
                direct_errors.append(str(exc))
        if direct_events:
            return _dedupe_events(direct_events)

        # The official Search API returns events with nested markets. Use it to
        # locate the one event by the two surnames before falling back to a
        # bounded date-wide event listing. Search is only discovery: the event
        # and authenticated market still must pass the strict structured gates.
        search_errors: list[str] = []
        search_client = getattr(self.client, "search", None)
        if search_client is not None and hasattr(search_client, "query"):
            search_terms = _event_search_terms(player, opponent)
            for query_text in search_terms:
                try:
                    payload = self._read_api(
                        lambda query_text=query_text: search_client.query(
                            {"query": query_text, "limit": 50, "page": 1}
                        ),
                        stage="event_discovery",
                        label=f"Polymarket event search for {query_text}",
                    ) or {}
                    matched = [
                        event
                        for event in _unwrap_list(payload, "events")
                        if _event_matches(event, player, opponent)
                    ]
                    if matched:
                        return _dedupe_events(matched)
                except RetryableExecutionError as exc:
                    search_errors.append(str(exc))

        query_sets: list[dict[str, Any]] = []
        if hinted_game_id not in (None, ""):
            try:
                query_sets.append(
                    {
                        "gameId": int(hinted_game_id),
                        "active": True,
                        "closed": False,
                        "ended": False,
                        "categories": ["sports"],
                        "limit": self.config.event_page_size,
                    }
                )
            except (TypeError, ValueError):
                pass
        query_sets.extend(_event_queries(record, self.config.event_page_size))

        errors: list[str] = list(direct_errors) + search_errors
        for params in query_sets:
            collected: dict[str, Mapping[str, Any]] = {}
            for page in range(max(1, self.config.event_page_limit)):
                query = dict(params)
                query["limit"] = self.config.event_page_size
                query["offset"] = page * self.config.event_page_size
                try:
                    payload = self._read_api(
                        lambda query=query: self.client.events.list(query),
                        stage="event_discovery",
                        label="Polymarket event query",
                    ) or {}
                except RetryableExecutionError as exc:
                    errors.append(str(exc))
                    break
                rows = _unwrap_list(payload, "events")
                for event in rows:
                    if _event_matches(event, player, opponent):
                        key = _event_identity(event)
                        collected[key] = event
                if len(rows) < self.config.event_page_size:
                    break
            if collected:
                # Queries are ordered by strongest hint/date. Once one query
                # scope contains the pair, do not widen into adjacent dates.
                return list(collected.values())

        if errors:
            raise RetryableExecutionError(
                "Polymarket event discovery failed without a usable match: "
                + "; ".join(errors[-3:]),
                "event_discovery",
            )
        return []

    @staticmethod
    def _choose_event(
        events: Sequence[Mapping[str, Any]],
        record: Mapping[str, Any],
        player: str,
        opponent: str,
    ) -> Mapping[str, Any]:
        scored = sorted(
            ((_event_score(event, record, player, opponent), event) for event in events),
            key=lambda item: item[0],
            reverse=True,
        )
        if not scored:
            raise RetryableExecutionError("No matching event remained after validation.", "event_discovery")
        top_score = scored[0][0]
        top = [event for score, event in scored if score == top_score]
        ids = {
            str(event.get("gameId") or event.get("id") or event.get("slug") or "")
            for event in top
        }
        if len(ids) > 1:
            raise PermanentExecutionError(
                f"More than one Polymarket event matched both players equally: {sorted(ids)}",
                "event_discovery",
            )
        return top[0]

    def _event_markets(self, event: Mapping[str, Any]) -> list[Mapping[str, Any]]:
        candidates: dict[str, Mapping[str, Any]] = {}

        def add(rows: Sequence[Any]) -> None:
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                slug = str(row.get("slug") or "").strip()
                if slug:
                    candidates[slug] = row

        add(list(event.get("markets") or []))
        game_id = event.get("gameId")
        event_slug = str(event.get("slug") or "").strip()
        queries: list[dict[str, Any]] = []
        if game_id not in (None, ""):
            try:
                queries.append({"gameId": int(game_id), "active": True, "closed": False, "limit": 100})
            except (TypeError, ValueError):
                pass
        if event_slug:
            queries.append({"eventSlug": [event_slug], "active": True, "closed": False, "limit": 100})
        errors: list[str] = []
        for query in queries:
            try:
                payload = self._read_api(
                    lambda query=query: self.client.markets.list(query),
                    stage="market_selection",
                    label="Polymarket event-market query",
                ) or {}
                add(_unwrap_list(payload, "markets"))
            except RetryableExecutionError as exc:
                errors.append(str(exc))
        if candidates:
            return list(candidates.values())
        if errors:
            raise RetryableExecutionError(
                "Polymarket could not list markets for the matched event: "
                + "; ".join(errors[-2:]),
                "market_selection",
            )
        return []

    def _open_orders(self, slug: str) -> Mapping[str, Any]:
        payload = self.client.orders.list({"slugs": [slug]})
        return payload if isinstance(payload, Mapping) else {}

    def _positions(self, slug: str) -> Mapping[str, Any]:
        payload = self.client.portfolio.positions({"market": slug, "limit": 100})
        return payload if isinstance(payload, Mapping) else {}

    def _activities(self, slug: str) -> Mapping[str, Any]:
        payload = self.client.portfolio.activities(
            {
                "marketSlug": slug,
                "types": ["ACTIVITY_TYPE_TRADE"],
                "sortOrder": "SORT_ORDER_DESCENDING",
                "limit": 20,
            }
        )
        return payload if isinstance(payload, Mapping) else {}

    def _preview(self, order_request: Mapping[str, Any]) -> Mapping[str, Any]:
        # The deployed polymarket-us==0.1.2 REST preview endpoint requires the
        # order under a top-level ``request`` field. Sending the order fields
        # directly produces HTTP 400: "Request is required". Order creation
        # remains direct because /v1/orders uses a different request schema.
        payload = self._read_api(
            lambda: self.client.orders.preview({"request": dict(order_request)}),
            stage="preview",
            label="Polymarket order preview",
        )
        return payload if isinstance(payload, Mapping) else {}

    def _confirm_order(
        self,
        order_id: str,
        create_response: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        initial_status, _state, _reason, _filled = _interpret_order(create_response)
        if initial_status in {"EXECUTED", "REJECTED", "UNFILLED"}:
            return create_response
        if not order_id:
            raise RetryableExecutionError(
                "Polymarket accepted the request but returned no order identifier.",
                "order_status",
            )

        last: Mapping[str, Any] = create_response
        last_error = ""
        for attempt in range(max(1, self.config.order_status_attempts)):
            try:
                self._wait_for_api_slot()
                payload = self.client.orders.retrieve(order_id) or {}
                if isinstance(payload, Mapping) and payload:
                    last = payload
                    status, _state, _reason, _filled = _interpret_order(payload)
                    if status in {"EXECUTED", "REJECTED", "UNFILLED"}:
                        return payload
            except Exception as exc:
                last_error = _safe_exception_message(exc)
                if _is_edge_rate_limit(exc) and attempt + 1 < self.config.order_status_attempts:
                    self._rate_limit_delay(attempt)
            if attempt + 1 < self.config.order_status_attempts:
                time.sleep(min(1.0, 0.15 * (2**attempt)))
        # The order ID is authoritative evidence that the submission reached
        # Polymarket. Return the latest response rather than throwing away that
        # idempotency boundary when status polling is temporarily unavailable.
        if last_error:
            enriched = dict(last)
            enriched["_status_poll_error"] = last_error
            return enriched
        return last


class ExecutionError(RuntimeError):
    def __init__(self, message: str, stage: str) -> None:
        super().__init__(message)
        self.stage = stage


class RetryableExecutionError(ExecutionError):
    pass


class PermanentExecutionError(ExecutionError):
    pass


class PermanentAPIExecutionError(PermanentExecutionError):
    def __init__(self, message: str, stage: str, *, status_code: int | None = None) -> None:
        super().__init__(message, stage)
        self.status_code = status_code


def _exception_status_code(exc: Exception) -> int | None:
    value = getattr(exc, "status_code", None)
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _exception_text(exc: Exception | None) -> str:
    if exc is None:
        return ""
    return str(exc or "").strip()


def _is_edge_rate_limit(exc: Exception) -> bool:
    """Identify only definite HTTP/Cloudflare throttles that are safe to retry."""

    if type(exc).__name__ == "RateLimitError" or _exception_status_code(exc) == 429:
        return True
    text = _exception_text(exc).casefold()
    markers = (
        "error 1015",
        "errorcode: 1015",
        "errorcode\":1015",
        "cloudflare to restrict access",
        "you are being rate limited",
        "temporarily rate limited",
        "too many requests",
        "http 429",
        "status 429",
    )
    return any(marker in text for marker in markers)


def _safe_exception_message(exc: Exception | None) -> str:
    text = _exception_text(exc)
    if _is_edge_rate_limit(exc) if exc is not None else False:
        return "Polymarket/Cloudflare temporarily rate-limited the request (1015/429)."
    if not text:
        return "unknown error"
    # Never send an entire HTML edge page to Railway/Discord.
    if "<!doctype html" in text.casefold() or "<html" in text.casefold():
        return "Polymarket returned an HTML error page instead of an API response."
    return " ".join(text.split())[:500]


def _is_definitive_api_rejection(exc: Exception) -> bool:
    if _is_edge_rate_limit(exc):
        return False
    name = type(exc).__name__
    if name in {"AuthenticationError", "BadRequestError", "NotFoundError", "PermissionDeniedError"}:
        return True
    status = _exception_status_code(exc)
    return status in {400, 401, 403, 404, 405, 422}


def _is_explicit_rate_limit_rejection(exc: Exception) -> bool:
    # Backward-compatible alias used by older tests/imports.
    return _is_edge_rate_limit(exc)


def _normalize_name(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-zA-Z0-9]+", " ", ascii_value).lower().split())


def _name_parts(value: str) -> tuple[list[str], str]:
    tokens = _normalize_name(value).split()
    return tokens[:-1], tokens[-1] if tokens else ""


def _name_signatures(value: str) -> list[tuple[list[str], str]]:
    tokens = _normalize_name(value).split()
    if not tokens:
        return []
    signatures = [(tokens[:-1], tokens[-1])]
    # Authenticated sports payloads occasionally use "Surname, Given".
    if len(tokens) >= 2:
        signatures.append((tokens[1:], tokens[0]))
    return signatures


def _given_names_compatible(first: list[str], second: list[str]) -> bool:
    if not first or not second:
        return True
    shorter, longer = (first, second) if len(first) <= len(second) else (second, first)
    for index, token in enumerate(shorter):
        if index >= len(longer):
            return False
        other = longer[index]
        if not token or not other or token[0] != other[0]:
            return False
        if len(token) > 1 and len(other) > 1 and token != other:
            return False
    return True


def _names_match(expected: str, candidate: str) -> bool:
    for expected_given, expected_surname in _name_signatures(expected):
        if not expected_surname:
            continue
        for candidate_given, candidate_surname in _name_signatures(candidate):
            if expected_surname == candidate_surname and _given_names_compatible(
                expected_given, candidate_given
            ):
                return True
    return False


def _side_name(side: Mapping[str, Any]) -> str:
    team = side.get("team")
    if isinstance(team, Mapping):
        for key in ("name", "displayName", "safeName", "alias", "abbreviation"):
            value = str(team.get(key) or "").strip()
            if value:
                return value
    for key in ("name", "title", "description", "outcome"):
        value = str(side.get(key) or "").strip()
        if value:
            return value
    return ""


def _market_sides(market: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for key in ("marketSides", "sides"):
        value = market.get(key)
        if isinstance(value, list):
            return [side for side in value if isinstance(side, Mapping)]
    return []


def _market_question(market: Mapping[str, Any]) -> str:
    return str(market.get("question") or market.get("title") or "").strip()


def _market_type(market: Mapping[str, Any]) -> str:
    for key in ("sportsMarketTypeV2", "sportsMarketType", "marketType", "type"):
        value = str(market.get(key) or "").strip()
        if value:
            return value
    return ""


def _explicit_moneyline(market: Mapping[str, Any]) -> bool:
    return _market_type(market).upper() in MONEYLINE_TYPES


def _validated_market_side(market: Mapping[str, Any], player: str, opponent: str) -> str:
    if not market:
        raise RetryableExecutionError("Authenticated market payload was empty.", "market_validation")
    if market.get("active") is False or market.get("closed") is True:
        raise RetryableExecutionError("Authenticated market is not active and open.", "market_validation")

    market_type = _market_type(market).upper()
    text = _normalize_name(
        " ".join(
            str(market.get(key) or "")
            for key in ("question", "title", "description", "slug", "spreadTotalSuffix")
        )
    ).upper()
    if market_type and market_type not in MONEYLINE_TYPES:
        raise PermanentExecutionError(f"not_moneyline:{market_type}", "market_validation")
    if any(re.search(pattern, text) for pattern in NON_MONEYLINE_PATTERNS):
        raise PermanentExecutionError("not_moneyline:text_marker", "market_validation")
    line = market.get("line")
    if line not in (None, "", 0, 0.0, "0", "0.0"):
        raise PermanentExecutionError("not_moneyline:line_present", "market_validation")

    sides = _market_sides(market)
    if len(sides) != 2:
        raise PermanentExecutionError("Market does not contain exactly two structured sides.", "market_validation")
    names = [_side_name(side) for side in sides]
    player_matches = [index for index, name in enumerate(names) if _names_match(player, name)]
    opponent_matches = [index for index, name in enumerate(names) if _names_match(opponent, name)]
    if len(player_matches) != 1 or len(opponent_matches) != 1:
        raise PermanentExecutionError(
            f"Market sides do not map uniquely to both players: {names}",
            "market_validation",
        )
    if player_matches[0] == opponent_matches[0]:
        raise PermanentExecutionError("Both scanner players mapped to the same market side.", "market_validation")
    long_values = [_side_long_flag(side) for side in sides]
    if set(long_values) != {False, True}:
        raise PermanentExecutionError("Market sides do not contain one LONG and one SHORT contract.", "market_validation")
    return LONG_SIDE if long_values[player_matches[0]] is True else SHORT_SIDE


def _side_long_flag(side: Mapping[str, Any]) -> bool | None:
    value = side.get("long")
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().upper()
    if text in {"TRUE", "1", "YES", "LONG"}:
        return True
    if text in {"FALSE", "0", "NO", "SHORT"}:
        return False
    for key in ("outcome", "side", "positionSide"):
        text = str(side.get(key) or "").strip().upper()
        if text in {"YES", "LONG", "OUTCOME_SIDE_YES", "POSITION_SIDE_LONG"}:
            return True
        if text in {"NO", "SHORT", "OUTCOME_SIDE_NO", "POSITION_SIDE_SHORT"}:
            return False
    return None


def _event_participants(event: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("teams", "participants"):
        value = event.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, Mapping):
                name = str(
                    item.get("name")
                    or item.get("displayName")
                    or item.get("safeName")
                    or item.get("title")
                    or ""
                ).strip()
            else:
                name = str(item or "").strip()
            if name and _normalize_name(name) not in {_normalize_name(existing) for existing in names}:
                names.append(name)
    for market in list(event.get("markets") or []):
        if isinstance(market, Mapping):
            for side in _market_sides(market):
                name = _side_name(side)
                if name and _normalize_name(name) not in {_normalize_name(existing) for existing in names}:
                    names.append(name)
    return names


def _event_text(event: Mapping[str, Any]) -> str:
    return " ".join(
        str(event.get(key) or "")
        for key in ("title", "subtitle", "description", "slug", "seriesSlug", "category", "subcategory")
    )


def _event_matches(event: Mapping[str, Any], player: str, opponent: str) -> bool:
    if event.get("closed") is True or event.get("ended") is True:
        return False
    participants = _event_participants(event)
    if participants:
        p = [name for name in participants if _names_match(player, name)]
        o = [name for name in participants if _names_match(opponent, name)]
        if p and o and _normalize_name(p[0]) != _normalize_name(o[0]):
            return True
    text = _event_text(event)
    return _name_in_text(player, text) and _name_in_text(opponent, text)


def _name_in_text(name: str, text: str) -> bool:
    normalized = _normalize_name(text)
    given, surname = _name_parts(name)
    if not surname or not re.search(rf"\b{re.escape(surname)}\b", normalized):
        return False
    if not given:
        return True
    return any(re.search(rf"\b{re.escape(token[0])}\w*\b", normalized) for token in given if token)


def _event_search_terms(player: str, opponent: str) -> list[str]:
    _player_given, player_surname = _name_parts(player)
    _opponent_given, opponent_surname = _name_parts(opponent)
    terms: list[str] = []
    if player_surname and opponent_surname:
        terms.append(f"{player_surname} {opponent_surname}")
    full = f"{_normalize_name(player)} {_normalize_name(opponent)}".strip()
    if full and full not in terms:
        terms.append(full)
    return terms


def _event_identity(event: Mapping[str, Any]) -> str:
    return str(
        event.get("gameId")
        or event.get("id")
        or event.get("eventId")
        or event.get("slug")
        or _event_text(event)
    )


def _dedupe_events(events: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return list({_event_identity(event): event for event in events}.values())


def _event_score(
    event: Mapping[str, Any],
    record: Mapping[str, Any],
    player: str,
    opponent: str,
) -> int:
    score = 100 if _event_participants(event) else 70
    text = _normalize_name(_event_text(event))
    tournament = _normalize_name(str(record.get("tournament") or record.get("competition_group") or ""))
    if tournament:
        tournament_tokens = [token for token in tournament.split() if len(token) >= 3]
        score += min(12, 3 * sum(token in text for token in tournament_tokens))
    if event.get("live") is True:
        score += 8
    target_date = _record_date(record)
    event_date = _parse_date(event.get("eventDate") or event.get("startTime") or event.get("startDate"))
    if target_date and event_date:
        delta = abs((event_date - target_date).days)
        score += max(0, 12 - delta * 6)
    if _name_in_text(player, text) and _name_in_text(opponent, text):
        score += 6
    return score


def _event_queries(record: Mapping[str, Any], page_size: int) -> list[dict[str, Any]]:
    target = _record_date(record)
    dates: list[date] = []
    if target:
        dates = [target, target - timedelta(days=1), target + timedelta(days=1)]
    queries: list[dict[str, Any]] = []
    for value in dates:
        queries.append(
            {
                "active": True,
                "closed": False,
                "ended": False,
                "categories": ["sports"],
                "eventDate": value.isoformat(),
                "limit": page_size,
            }
        )
    if not queries:
        now = datetime.now(timezone.utc)
        queries.append(
            {
                "active": True,
                "closed": False,
                "ended": False,
                "categories": ["sports"],
                "startTimeMin": (now - timedelta(days=1)).isoformat(),
                "startTimeMax": (now + timedelta(days=2)).isoformat(),
                "limit": page_size,
            }
        )
    return queries


def _record_date(record: Mapping[str, Any]) -> date | None:
    for key in ("event_date", "event_time", "scanned_at"):
        parsed = _parse_date(record.get(key))
        if parsed:
            return parsed
    return None


def _parse_date(value: Any) -> date | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        pass
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _unwrap_market(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    nested = payload.get("market") if isinstance(payload, Mapping) else None
    return nested if isinstance(nested, Mapping) else payload


def _unwrap_book(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in ("marketData", "book"):
        nested = payload.get(key) if isinstance(payload, Mapping) else None
        if isinstance(nested, Mapping):
            return nested
    return payload


def _unwrap_list(payload: Mapping[str, Any], key: str) -> list[Mapping[str, Any]]:
    value = payload.get(key) if isinstance(payload, Mapping) else None
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _amount(value: Any) -> Decimal | None:
    if isinstance(value, Mapping):
        value = value.get("value")
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _best_yes_prices(book: Mapping[str, Any]) -> tuple[Decimal, Decimal]:
    """Return the visible YES BBO for telemetry without adding a trade gate."""

    bids = [
        price
        for level in list(book.get("bids") or [])
        if isinstance(level, Mapping) and (price := _amount(level.get("px"))) is not None
    ]
    offers = [
        price
        for level in list(book.get("offers") or [])
        if isinstance(level, Mapping) and (price := _amount(level.get("px"))) is not None
    ]
    return max(bids, default=Decimal("0")), min(offers, default=Decimal("0"))


def _execution_prices(book: Mapping[str, Any], side: str) -> tuple[Decimal, Decimal]:
    bids = [
        price
        for level in list(book.get("bids") or [])
        if isinstance(level, Mapping) and (price := _amount(level.get("px"))) is not None
    ]
    offers = [
        price
        for level in list(book.get("offers") or [])
        if isinstance(level, Mapping) and (price := _amount(level.get("px"))) is not None
    ]
    if side == LONG_SIDE:
        if not offers:
            raise RetryableExecutionError("No executable YES offer is available.", "order_book")
        long_price = min(offers)
        return long_price, long_price
    if side == SHORT_SIDE:
        if not bids:
            raise RetryableExecutionError("No executable NO offer is available.", "order_book")
        long_price = max(bids)
        return long_price, Decimal("1") - long_price
    raise PermanentExecutionError("Unknown market side.", "market_validation")


def _required_decimal(market: Mapping[str, Any], key: str) -> Decimal:
    value = market.get(key)
    parsed = _amount(value)
    if parsed is None:
        return Decimal("0")
    return parsed


def _usd_balance(payload: Mapping[str, Any]) -> tuple[Decimal, Decimal]:
    balances = payload.get("balances") if isinstance(payload, Mapping) else None
    rows = list(balances or []) if isinstance(balances, (list, tuple)) else []
    selected: Mapping[str, Any] | None = None
    for row in rows:
        if isinstance(row, Mapping) and str(row.get("currency") or "").upper() == "USD":
            selected = row
            break
    if selected is None and rows and isinstance(rows[0], Mapping):
        selected = rows[0]
    if selected is None:
        raise RetryableExecutionError("No USD account balance was returned.", "sizing")
    current = _amount(selected.get("currentBalance")) or Decimal("0")
    buying = _amount(selected.get("buyingPower"))
    if buying is None:
        buying = current
    if current <= 0 or buying <= 0:
        raise RetryableExecutionError("Account has no available USD buying power.", "sizing")
    return current, buying


def _stake_amount(balance: Decimal, buying_power: Decimal, pct: float) -> Decimal:
    requested = balance * Decimal(str(pct)) / Decimal("100")
    return min(requested, buying_power).quantize(Decimal("0.01"), rounding=ROUND_DOWN)


def _quantity_for_stake(stake: Decimal, player_price: Decimal, minimum_qty: Decimal) -> Decimal:
    if player_price <= 0 or minimum_qty <= 0:
        return Decimal("0")
    raw = stake / player_price
    units = (raw / minimum_qty).to_integral_value(rounding=ROUND_DOWN)
    return (units * minimum_qty).normalize()


def _align_price(price: Decimal, tick: Decimal) -> Decimal:
    if tick <= 0:
        return price
    units = (price / tick).to_integral_value(rounding=ROUND_DOWN)
    aligned = units * tick
    return min(Decimal("0.99"), max(Decimal("0.01"), aligned))


def _decimal_string(value: Decimal) -> str:
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _payload_orders(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return every concrete order object exposed by an SDK response."""

    orders: list[Mapping[str, Any]] = []
    nested = payload.get("order")
    if isinstance(nested, Mapping):
        orders.append(nested)
    if any(
        key in payload
        for key in (
            "marketSlug",
            "intent",
            "outcomeSide",
            "action",
            "state",
            "status",
        )
    ):
        orders.append(payload)
    for execution in list(payload.get("executions") or []):
        if isinstance(execution, Mapping) and isinstance(execution.get("order"), Mapping):
            orders.append(execution["order"])
    return orders


def _buy_outcome_side(order: Mapping[str, Any]) -> tuple[str, str]:
    """Resolve a returned buy order to YES or NO and detect contradictions."""

    intent = str(order.get("intent") or "").strip().upper()
    outcome_side = str(order.get("outcomeSide") or "").strip().upper()
    action = str(order.get("action") or "").strip().upper()
    intent_outcome = BUY_INTENT_TO_OUTCOME.get(intent, "")

    if outcome_side:
        if outcome_side not in {YES_OUTCOME_SIDE, NO_OUTCOME_SIDE}:
            return "", f"unknown outcome side {outcome_side}"
        if action and action != BUY_ACTION:
            return "", f"non-buy action {action}"
        if intent and not intent_outcome:
            return "", f"non-buy or unknown intent {intent}"
        if intent_outcome and intent_outcome != outcome_side:
            return "", (
                f"conflicting intent {intent} and outcome side {outcome_side}"
            )
        return outcome_side, ""

    if action:
        return "", f"action {action} was returned without outcomeSide"
    if intent:
        if not intent_outcome:
            return "", f"non-buy or unknown intent {intent}"
        return intent_outcome, ""
    return "", ""


def _validate_order_payload_contract(
    payload: Mapping[str, Any],
    *,
    expected_slug: str,
    expected_outcome_side: str,
    stage: str,
) -> None:
    """Reject any preview/order response that identifies another market or side.

    Older SDK responses may omit side fields, so absence is tolerated. Whenever
    Polymarket returns intent or outcomeSide/action, however, it must agree with
    the exact YES/NO contract selected from authenticated marketSides.
    """

    for order in _payload_orders(payload):
        returned_slug = str(order.get("marketSlug") or "").strip()
        if returned_slug and returned_slug.casefold() != expected_slug.casefold():
            raise PermanentExecutionError(
                f"Polymarket {stage} returned the wrong market slug: {returned_slug}",
                stage,
            )
        returned_outcome, error = _buy_outcome_side(order)
        if error:
            raise PermanentExecutionError(
                f"Polymarket {stage} returned an invalid order side contract: {error}",
                stage,
            )
        if returned_outcome and returned_outcome != expected_outcome_side:
            raise PermanentExecutionError(
                "Polymarket "
                f"{stage} returned {returned_outcome}, expected {expected_outcome_side}.",
                stage,
            )


def _find_exposure_order(payload: Mapping[str, Any], slug: str) -> Mapping[str, Any] | None:
    """Find an exact-market order that may represent live or filled exposure.

    Zero-fill canceled/rejected/expired orders are ignored. Pending orders and
    confirmed fills are exchange-side evidence used to suppress duplicates after
    a process restart.
    """

    expected = slug.casefold()
    for order in list(payload.get("orders") or []):
        if not isinstance(order, Mapping):
            continue
        order_slug = str(order.get("marketSlug") or "").casefold()
        if order_slug != expected:
            continue
        status, state, _reason, filled = _interpret_order(order)
        if status in {"EXECUTED", "PENDING"} or state in PENDING_ORDER_STATES or filled > 0:
            return order
    return None


def _find_open_order(payload: Mapping[str, Any], slug: str) -> Mapping[str, Any] | None:
    expected = slug.casefold()
    for order in list(payload.get("orders") or []):
        if not isinstance(order, Mapping):
            continue
        state = str(order.get("state") or "").upper()
        order_slug = str(order.get("marketSlug") or "").casefold()
        if order_slug == expected and state not in TERMINAL_ORDER_STATES:
            return order
    return None


def _has_open_order(payload: Mapping[str, Any], slug: str) -> bool:
    """Compatibility helper retained for tests and external imports."""
    return _find_open_order(payload, slug) is not None


def _has_position(payload: Mapping[str, Any], slug: str) -> bool:
    positions = payload.get("positions") if isinstance(payload, Mapping) else None
    if isinstance(positions, Mapping):
        iterable = positions.items()
    elif isinstance(positions, list):
        iterable = (("", item) for item in positions)
    else:
        return False
    expected = slug.casefold()
    for key, position in iterable:
        if not isinstance(position, Mapping) or position.get("expired") is True:
            continue
        metadata = position.get("marketMetadata")
        meta_slug = metadata.get("slug") if isinstance(metadata, Mapping) else ""
        candidate = str(key or position.get("marketSlug") or meta_slug or "").casefold()
        if candidate != expected:
            continue
        quantity = _amount(position.get("netPositionDecimal"))
        if quantity is None:
            quantity = _amount(position.get("netPosition"))
        return quantity is None or abs(quantity) > Decimal("0.0000001")
    return False


def _trade_quantity(trade: Mapping[str, Any]) -> Decimal | None:
    quantity = _amount(trade.get("qtyDecimal"))
    if quantity is None:
        quantity = _amount(trade.get("qty"))
    return quantity


def _find_trade_activity(payload: Mapping[str, Any], slug: str) -> Mapping[str, Any] | None:
    expected = slug.casefold()
    for activity in list(payload.get("activities") or []):
        if not isinstance(activity, Mapping):
            continue
        trade = activity.get("trade")
        if not isinstance(trade, Mapping):
            continue
        if str(trade.get("marketSlug") or "").casefold() != expected:
            continue
        state = str(trade.get("state") or "").upper()
        if state in {"TRADE_STATE_BUSTED", "TRADE_STATE_REJECTED"}:
            continue
        quantity = _trade_quantity(trade)
        # A trade activity with an unknown quantity is still exchange evidence
        # that an execution occurred. Only an explicit zero is ignored.
        if quantity is None or quantity > 0:
            return trade
    return None


def _order_id(payload: Mapping[str, Any]) -> str:
    direct = str(payload.get("id") or payload.get("orderId") or "").strip()
    if direct:
        return direct
    order = payload.get("order")
    if isinstance(order, Mapping):
        nested = str(order.get("id") or order.get("orderId") or "").strip()
        if nested:
            return nested
    for execution in list(payload.get("executions") or []):
        if isinstance(execution, Mapping) and isinstance(execution.get("order"), Mapping):
            nested = str(execution["order"].get("id") or "").strip()
            if nested:
                return nested
    return ""


def _retryable_order_outcome(
    status: str,
    state: str,
    reason: str,
    filled_quantity: float,
) -> bool:
    """Return True only when the exchange confirmed there was no fill risk.

    A zero-fill IOC cancellation is safe to try again on a later, still-valid
    scanner snapshot.  Exchange/preview rejections are retryable only for
    clearly temporary causes.  Invalid requests, authentication failures,
    market mismatches, and unknown pending states remain terminal.
    """

    normalized = " ".join((status, state, reason)).upper().replace("-", "_")
    if status == "UNFILLED" and filled_quantity <= 0:
        return True
    if status != "REJECTED" or filled_quantity > 0:
        return False
    return any(
        token in normalized
        for token in (
            "NO_LIQUIDITY",
            "EXCHANGE_CLOSED",
            "RATE_LIMIT",
            "TOO_MANY_REQUESTS",
            "TEMPORARY",
            "TEMPORARILY",
            "SERVICE_UNAVAILABLE",
            "PENDING_RISK",
        )
    )


def _interpret_order(payload: Mapping[str, Any]) -> tuple[str, str, str, float]:
    orders: list[Mapping[str, Any]] = []
    if isinstance(payload.get("order"), Mapping):
        orders.append(payload["order"])
    if any(key in payload for key in ("state", "status", "cumQuantity", "filledQuantity")):
        orders.append(payload)
    executions = [item for item in list(payload.get("executions") or []) if isinstance(item, Mapping)]
    for execution in executions:
        if isinstance(execution.get("order"), Mapping):
            orders.append(execution["order"])

    states = [str(order.get("state") or order.get("status") or "").upper() for order in orders]
    types = [str(execution.get("type") or "").upper() for execution in executions]
    raw_reasons: list[str] = []
    filled: list[Decimal] = []
    for order in orders:
        for key in ("orderRejectReason", "rejectReason", "reason", "error", "message"):
            text = str(order.get(key) or "").strip()
            if text:
                raw_reasons.append(text)
        for key in ("cumQuantity", "filledQuantity", "cumulativeQuantity"):
            value = _amount(order.get(key))
            if value is not None and value > 0:
                filled.append(value)
    for execution in executions:
        reject_text = str(execution.get("orderRejectReason") or "").strip()
        execution_text = str(execution.get("text") or "").strip()
        if reject_text:
            raw_reasons.append(reject_text)
        if execution_text:
            raw_reasons.append(execution_text)
        value = _amount(execution.get("lastShares") or execution.get("filledQuantity"))
        if value is not None and value > 0:
            filled.append(value)

    state = states[-1] if states else ""
    filled_qty = float(max(filled, default=Decimal("0")))
    joined_states = " ".join(states)
    joined_types = " ".join(types)
    reject_context = "REJECT" in joined_states or "REJECT" in joined_types
    reasons = [
        item
        for item in raw_reasons
        if reject_context or item.strip().upper() != DEFAULT_EXCHANGE_REJECT_REASON
    ]
    reason = reasons[-1] if reasons else ""

    # A confirmed fill always takes precedence over a later cancel/reject state.
    # IOC orders can partially fill and then cancel the remainder; reporting that
    # as REJECTED would hide real exposure and could trigger a duplicate retry.
    if filled_qty > 0 or "FILL" in joined_types or "FILLED" in joined_states:
        if (
            "PARTIAL" in joined_types
            or "PARTIAL" in joined_states
            or "REJECT" in joined_states
            or "REJECT" in joined_types
            or any(token in joined_states for token in ("CANCELED", "CANCELLED", "EXPIRED"))
            or any(token in joined_types for token in ("CANCELED", "EXPIRED"))
        ):
            return "EXECUTED", state, "Order partially filled; the remainder was not filled.", filled_qty
        return "EXECUTED", state, "Order fill confirmed.", filled_qty
    if "REJECT" in joined_states or "REJECT" in joined_types:
        return "REJECTED", state, reason or "Order was rejected by Polymarket.", filled_qty
    if any(token in joined_states for token in ("CANCELED", "CANCELLED", "EXPIRED")) or any(
        token in joined_types for token in ("CANCELED", "EXPIRED")
    ):
        time_in_force = " ".join(
            str(order.get("tif") or "").upper() for order in orders
        )
        fallback = (
            "IOC order expired or canceled without a fill because no executable quantity "
            "remained at the allowed price; no position was opened."
            if "IMMEDIATE_OR_CANCEL" in time_in_force
            else "Order ended without a fill; no position was opened."
        )
        return "UNFILLED", state, reason or fallback, 0.0
    if state in PENDING_ORDER_STATES or "NEW" in joined_types:
        return "PENDING", state, "Order was submitted and is awaiting a terminal exchange state.", 0.0
    if not payload:
        return "FAILED", "", "Polymarket returned an empty order response.", 0.0
    return "PENDING", state, "Order response was received but its final state is not yet known.", 0.0
