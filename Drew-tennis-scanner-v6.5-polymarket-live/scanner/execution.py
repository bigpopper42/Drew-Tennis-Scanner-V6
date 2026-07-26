"""Guarded Polymarket US execution for approved scanner trade records.

The tennis scanner remains the sole decision maker. This module independently
validates the selected Polymarket US market, sizes one market order from the
authenticated account balance, previews it, submits it, and reports the result.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from polymarket_us import PolymarketUS


OPEN_MARKET_STATE = "MARKET_STATE_OPEN"
LONG_SIDE = "Long / YES"
SHORT_SIDE = "Short / NO"


class ExecutionClient(Protocol):
    account: Any
    markets: Any
    orders: Any
    portfolio: Any

    def close(self) -> None: ...


@dataclass(frozen=True)
class ExecutionConfig:
    key_id: str
    secret_key: str
    bankroll_pct: float = 10.0
    minimum_order_usd: float = 0.50
    maximum_order_usd: float = 25.0
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
    account_balance: float = 0.0
    buying_power: float = 0.0
    stake_amount: float = 0.0
    player_price_cents: float = 0.0
    order_id: str = ""
    order_state: str = ""

    @property
    def order_created(self) -> bool:
        return self.status in {"EXECUTED", "SUBMITTED"}

    def log_fields(self) -> dict[str, Any]:
        return {
            "execution_status": self.status,
            "execution_reason": self.reason,
            "signal_key": self.signal_key,
            "player": self.player,
            "opponent": self.opponent,
            "market_slug": self.market_slug,
            "market_side": self.market_side,
            "account_balance": self.account_balance,
            "buying_power": self.buying_power,
            "stake_amount": self.stake_amount,
            "player_price_cents": self.player_price_cents,
            "order_id": self.order_id,
            "order_state": self.order_state,
        }


class PolymarketExecutionEngine:
    """Place at most one guarded Polymarket US order for a scanner signal."""

    def __init__(
        self,
        config: ExecutionConfig,
        *,
        client: ExecutionClient | None = None,
    ) -> None:
        self.config = config
        self.client: ExecutionClient = client or PolymarketUS(
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

        def reject(reason: str, **fields: Any) -> ExecutionResult:
            return ExecutionResult(
                status="REJECTED",
                reason=reason,
                signal_key=signal_key,
                player=player,
                opponent=opponent,
                market_slug=market_slug,
                market_side=market_side,
                **fields,
            )

        if record.get("decision_status") != "TRADE":
            return reject("Scanner record is not an approved TRADE.")
        if not record.get("alert_eligible"):
            return reject("Scanner record is not eligible for a new trade alert.")
        if not record.get("market_found") or not market_slug:
            return reject("Polymarket US market was not safely matched.")
        if market_side not in {LONG_SIDE, SHORT_SIDE}:
            return reject("Backed player could not be mapped safely to YES or NO.")
        try:
            confidence = float(record.get("market_match_confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence < self.config.minimum_market_confidence:
            return reject(
                "Market match confidence is below the execution minimum."
            )

        try:
            open_orders = self.client.orders.list()
            if list((open_orders or {}).get("orders") or []):
                return reject("Another Polymarket order is already open.")

            positions = self.client.portfolio.positions({"limit": 100})
            if self._has_open_position(positions):
                return reject("Another Polymarket position is already open.")

            market_payload = self.client.markets.retrieve_by_slug(market_slug)
            market = (market_payload or {}).get("market") or {}
            if not isinstance(market, Mapping) or not market:
                return reject("Polymarket US did not return the matched market.")
            if market.get("active") is not True or market.get("closed") is True:
                return reject("Polymarket market is not active and tradable.")
            if not self._market_names_match(market, player, opponent):
                return reject("Live market names do not match the scanner signal.")

            book = self.client.markets.book(market_slug) or {}
            if str(book.get("state") or "") != OPEN_MARKET_STATE:
                return reject("Polymarket order book is suspended, halted, or closed.")

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
            if stake_amount < self.config.minimum_order_usd:
                return reject(
                    "Calculated 10% stake is below the minimum live order.",
                    account_balance=account_balance,
                    buying_power=buying_power,
                    stake_amount=stake_amount,
                    player_price_cents=player_price_cents,
                )
            if stake_amount > self.config.maximum_order_usd:
                return reject(
                    "Calculated 10% stake exceeds the configured order cap.",
                    account_balance=account_balance,
                    buying_power=buying_power,
                    stake_amount=stake_amount,
                    player_price_cents=player_price_cents,
                )

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
                        "value": self._price_string(long_reference),
                        "currency": "USD",
                    },
                    "ticks": self.config.slippage_ticks,
                },
            }

            # Preview validates the exact request without moving money.
            self.client.orders.preview({"request": order_request})
            response = self.client.orders.create(order_request) or {}
        except Exception as exc:
            return ExecutionResult(
                status="FAILED",
                reason=f"Polymarket API request failed: {exc}",
                signal_key=signal_key,
                player=player,
                opponent=opponent,
                market_slug=market_slug,
                market_side=market_side,
            )

        order_id = str(response.get("id") or "")
        execution_status, order_state, reason = self._interpret_order_response(response)
        return ExecutionResult(
            status=execution_status,
            reason=reason,
            signal_key=signal_key,
            player=player,
            opponent=opponent,
            market_slug=market_slug,
            market_side=market_side,
            account_balance=account_balance,
            buying_power=buying_power,
            stake_amount=stake_amount,
            player_price_cents=player_price_cents,
            order_id=order_id,
            order_state=order_state,
        )

    @staticmethod
    def signal_key(record: Mapping[str, Any]) -> str:
        return str(
            record.get("trade_key")
            or f"{record.get('event_key')}|{str(record.get('player') or '').casefold()}"
        )

    @staticmethod
    def _has_open_position(payload: Mapping[str, Any]) -> bool:
        positions = payload.get("positions") or {}
        values = positions.values() if isinstance(positions, Mapping) else positions
        for position in values or []:
            if not isinstance(position, Mapping) or position.get("expired") is True:
                continue
            raw = position.get("netPosition")
            try:
                if abs(float(raw or 0.0)) > 0.000001:
                    return True
            except (TypeError, ValueError):
                return True
        return False

    @staticmethod
    def _market_names_match(
        market: Mapping[str, Any], player: str, opponent: str
    ) -> bool:
        haystack = _normalize(
            " ".join(
                [
                    str(market.get("title") or ""),
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

    @staticmethod
    def _interpret_order_response(
        response: Mapping[str, Any],
    ) -> tuple[str, str, str]:
        executions = list(response.get("executions") or [])
        states: list[str] = []
        types: list[str] = []
        rejection_text: list[str] = []
        for execution in executions:
            if not isinstance(execution, Mapping):
                continue
            execution_type = str(execution.get("type") or "")
            if execution_type:
                types.append(execution_type)
            order = execution.get("order") or {}
            if isinstance(order, Mapping):
                state = str(order.get("state") or "")
                if state:
                    states.append(state)
            text = str(
                execution.get("orderRejectReason")
                or execution.get("text")
                or ""
            ).strip()
            if text:
                rejection_text.append(text)

        order_state = states[-1] if states else ""
        if "EXECUTION_TYPE_REJECTED" in types or "ORDER_STATE_REJECTED" in states:
            return (
                "REJECTED",
                order_state,
                rejection_text[-1] if rejection_text else "Order was rejected.",
            )
        if "EXECUTION_TYPE_FILL" in types or "ORDER_STATE_FILLED" in states:
            return "EXECUTED", order_state, "Order filled."
        if (
            "EXECUTION_TYPE_PARTIAL_FILL" in types
            or "ORDER_STATE_PARTIALLY_FILLED" in states
        ):
            return "EXECUTED", order_state, "Order partially filled; remainder canceled."
        if response.get("id"):
            return "SUBMITTED", order_state, "Order accepted by Polymarket US."
        return "FAILED", order_state, "Polymarket returned no order identifier."

    @staticmethod
    def _price_string(value: float) -> str:
        return f"{value:.4f}".rstrip("0").rstrip(".")


def _amount_value(value: Any) -> float | None:
    if isinstance(value, Mapping):
        value = value.get("value")
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if 0.0 < number < 1.0 else None


def _normalize(value: str) -> str:
    ascii_text = (
        unicodedata.normalize("NFKD", value or "")
        .encode("ascii", "ignore")
        .decode()
    )
    return " ".join(re.sub(r"[^a-zA-Z0-9 ]+", " ", ascii_text).lower().split())


def _surname_matches(name: str, haystack: str) -> bool:
    normalized = _normalize(name)
    surname = normalized.split()[-1] if normalized else ""
    return len(surname) >= 3 and surname in set(haystack.split())
