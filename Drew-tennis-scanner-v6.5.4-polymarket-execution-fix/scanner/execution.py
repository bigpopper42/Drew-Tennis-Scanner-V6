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
            market = _market_payload(market_payload)
            if not market:
                return reject("Polymarket US did not return the matched market.")
            if market.get("active") is not True or market.get("closed") is True:
                return reject("Polymarket market is not active and tradable.")
            if not self._market_names_match(market, player, opponent):
                return reject("Live market names do not match the scanner signal.")

            live_market_side = self._live_market_side(market, player, opponent)
            if live_market_side in {LONG_SIDE, SHORT_SIDE}:
                market_side = live_market_side
            elif market_side not in {LONG_SIDE, SHORT_SIDE}:
                return reject("Backed player could not be mapped safely to YES or NO.")

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
    if isinstance(team, Mapping):
        for key in ("name", "displayName", "safeName", "alias", "abbreviation"):
            value = str(team.get(key) or "").strip()
            if value and _normalize(value) not in {_normalize(item) for item in names}:
                names.append(value)
    for key in ("name", "displayName", "safeName", "alias", "abbreviation"):
        value = str(side.get(key) or "").strip()
        if value and _normalize(value) not in {_normalize(item) for item in names}:
            names.append(value)
    return names


def _structured_market_sides(market: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_sides = market.get("marketSides")
    if not isinstance(raw_sides, list):
        return []
    sides: list[dict[str, Any]] = []
    for raw_side in raw_sides:
        if not isinstance(raw_side, Mapping) or not isinstance(raw_side.get("long"), bool):
            continue
        names = _team_names(raw_side)
        if not names:
            continue
        sides.append({"long": bool(raw_side["long"]), "names": names})
    return sides


def _surname_sequences_agree(left: list[str], right: list[str]) -> bool:
    if not left or not right:
        return False
    if left == right:
        return True
    shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
    width = len(shorter)
    return any(longer[index : index + width] == shorter for index in range(len(longer) - width + 1))


def _name_match_score(expected: str, candidate: str) -> float:
    left = _normalize(expected)
    right = _normalize(candidate)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0

    left_tokens = left.split()
    right_tokens = right.split()
    if len(left_tokens) < 2 or len(right_tokens) < 2:
        return 0.0

    left_first, right_first = left_tokens[0], right_tokens[0]
    left_surnames, right_surnames = left_tokens[1:], right_tokens[1:]
    if not _surname_sequences_agree(left_surnames, right_surnames):
        return 0.0

    exact_surnames = left_surnames == right_surnames
    if left_first == right_first:
        return 0.99 if exact_surnames else 0.96
    if (len(left_first) == 1 or len(right_first) == 1) and left_first[0] == right_first[0]:
        return 0.97 if exact_surnames else 0.94
    return 0.0


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
    surname_tokens = tokens[1:]
    return bool(surname_tokens) and all(
        len(token) >= 3 and token in haystack_tokens for token in surname_tokens
    )
