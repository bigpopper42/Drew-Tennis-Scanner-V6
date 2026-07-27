from __future__ import annotations

from typing import Any

from scanner.execution import (
    ExecutionConfig,
    ExecutionResult,
    LONG_SIDE,
    SHORT_SIDE,
    PolymarketExecutionEngine,
    _live_market_side,
)
from scanner.worker_runtime import CycleReport, RailwayShadowWorker, WorkerConfig


class FakeAccount:
    def __init__(self, balance: float = 8.0, buying_power: float = 8.0) -> None:
        self.balance = balance
        self.buying_power = buying_power

    def balances(self) -> dict[str, Any]:
        return {
            "balances": [
                {
                    "currency": "USD",
                    "currentBalance": self.balance,
                    "buyingPower": self.buying_power,
                }
            ]
        }


class FakePortfolio:
    def __init__(self, positions: dict[str, Any] | None = None) -> None:
        self.payload = {"positions": positions or {}}

    def positions(self, _params: dict[str, Any]) -> dict[str, Any]:
        return self.payload


class FakeMarkets:
    def __init__(
        self,
        *,
        active: bool = True,
        closed: bool = False,
        state: str = "MARKET_STATE_OPEN",
        bid: float = 0.32,
        ask: float = 0.68,
        title: str = "Alex Hernandez vs Nicolas Mejia",
        market_sides: list[dict[str, Any]] | None = None,
    ) -> None:
        self.market = {
            "market": {
                "slug": "aec-atp-hernandez-mejia-2026-07-25",
                "title": title,
                "description": "Who will win?",
                "active": active,
                "closed": closed,
            }
        }
        if market_sides is not None:
            self.market["market"]["marketSides"] = market_sides
        self.book_payload = {
            "marketSlug": "aec-atp-hernandez-mejia-2026-07-25",
            "state": state,
            "bids": [{"px": {"value": str(bid), "currency": "USD"}, "qty": "10"}],
            "offers": [{"px": {"value": str(ask), "currency": "USD"}, "qty": "10"}],
        }

    def retrieve_by_slug(self, _slug: str) -> dict[str, Any]:
        return self.market

    def book(self, _slug: str) -> dict[str, Any]:
        return self.book_payload


class FakeOrders:
    def __init__(
        self,
        *,
        open_orders: list[dict[str, Any]] | None = None,
        rejected: bool = False,
    ) -> None:
        self.open_orders = open_orders or []
        self.rejected = rejected
        self.preview_calls: list[dict[str, Any]] = []
        self.create_calls: list[dict[str, Any]] = []

    def list(self) -> dict[str, Any]:
        return {"orders": self.open_orders}

    def preview(self, params: dict[str, Any]) -> dict[str, Any]:
        self.preview_calls.append(params)
        return {"order": params["request"]}

    def create(self, params: dict[str, Any]) -> dict[str, Any]:
        self.create_calls.append(params)
        if self.rejected:
            return {
                "id": "rejected-1",
                "executions": [
                    {
                        "type": "EXECUTION_TYPE_REJECTED",
                        "orderRejectReason": "NO_LIQUIDITY",
                        "order": {"state": "ORDER_STATE_REJECTED"},
                    }
                ],
            }
        return {
            "id": "order-1",
            "executions": [
                {
                    "type": "EXECUTION_TYPE_FILL",
                    "order": {"state": "ORDER_STATE_FILLED"},
                }
            ],
        }


class FakeClient:
    def __init__(
        self,
        *,
        account: FakeAccount | None = None,
        portfolio: FakePortfolio | None = None,
        markets: FakeMarkets | None = None,
        orders: FakeOrders | None = None,
    ) -> None:
        self.account = account or FakeAccount()
        self.portfolio = portfolio or FakePortfolio()
        self.markets = markets or FakeMarkets()
        self.orders = orders or FakeOrders()
        self.closed = False

    def close(self) -> None:
        self.closed = True


def config(**changes: Any) -> ExecutionConfig:
    values = {
        "key_id": "key-id",
        "secret_key": "secret-key",
        "bankroll_pct": 10.0,
        "minimum_order_usd": 0.50,
        "maximum_order_usd": 25.0,
        "minimum_price_cents": 50.0,
        "maximum_price_cents": 99.0,
        "slippage_ticks": 1,
        "minimum_market_confidence": 80.0,
    }
    values.update(changes)
    return ExecutionConfig(**values)


def record(*, side: str = LONG_SIDE) -> dict[str, Any]:
    return {
        "decision_status": "TRADE",
        "alert_eligible": True,
        "trade_key": "event-1|alex hernandez",
        "event_key": "event-1",
        "player": "Alex Hernandez",
        "opponent": "Nicolas Mejia",
        "market_found": True,
        "market_slug": "aec-atp-hernandez-mejia-2026-07-25",
        "market_side": side,
        "market_match_confidence": 95.0,
    }


def test_live_long_order_uses_ten_percent_cash_and_automatic_indicator() -> None:
    client = FakeClient()
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record())

    assert result.status == "EXECUTED"
    assert result.stake_amount == 0.80
    assert result.player_price_cents == 68.0
    request = client.orders.create_calls[0]
    assert request["cashOrderQty"]["value"] == "0.80"
    assert request["intent"] == "ORDER_INTENT_BUY_LONG"
    assert request["manualOrderIndicator"] == "MANUAL_ORDER_INDICATOR_AUTOMATIC"
    assert request["tif"] == "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL"
    assert len(client.orders.preview_calls) == 1


def test_short_side_uses_inverse_player_price_and_short_intent() -> None:
    client = FakeClient()
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record(side=SHORT_SIDE))

    assert result.status == "EXECUTED"
    assert result.player_price_cents == 68.0
    request = client.orders.create_calls[0]
    assert request["intent"] == "ORDER_INTENT_BUY_SHORT"
    assert request["slippageTolerance"]["currentPrice"]["value"] == "0.32"


def test_missing_discovery_side_uses_authenticated_live_mapping() -> None:
    market_sides = [
        {"team": {"name": "Alex Hernandez"}, "long": True},
        {"team": {"name": "Nicolas Mejia"}, "long": False},
    ]
    client = FakeClient(
        markets=FakeMarkets(title="Men's tennis match", market_sides=market_sides)
    )
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record(side=""))

    assert result.status == "EXECUTED"
    assert result.market_side == LONG_SIDE
    assert client.orders.create_calls[0]["intent"] == "ORDER_INTENT_BUY_LONG"


def test_generic_title_validates_from_live_monteiro_mazza_sides() -> None:
    market = {
        "title": "Men's tennis match winner",
        "slug": "generic-tennis-market",
        "description": "Live event",
        "marketSides": [
            {
                "team": {
                    "name": "Thiago Monteiro",
                    "displayName": "T. Monteiro",
                },
                "long": False,
            },
            {
                "team": {
                    "name": "Matteo Mazza",
                    "abbreviation": "M. Mazza",
                },
                "long": True,
            },
        ],
    }

    assert PolymarketExecutionEngine._market_names_match(
        market, "T. Monteiro", "M. Mazza"
    )
    assert _live_market_side(market, "Thiago Monteiro", "Matteo Mazza") == SHORT_SIDE
    assert _live_market_side(market, "Matteo Mazza", "Thiago Monteiro") == LONG_SIDE


def test_full_first_names_and_initials_match_when_surnames_agree() -> None:
    market = {
        "marketSides": [
            {"team": {"name": "Thiago Monteiro"}, "long": True},
            {"team": {"displayName": "M. Mazza"}, "long": False},
        ]
    }

    assert _live_market_side(market, "T. Monteiro", "Matteo Mazza") == LONG_SIDE
    assert _live_market_side(market, "Matteo Mazza", "Thiago Monteiro") == SHORT_SIDE


def test_two_competitors_cannot_map_to_the_same_side() -> None:
    market = {
        "marketSides": [
            {
                "team": {
                    "name": "Alex Smith",
                    "alias": "Andrew Smith",
                },
                "long": True,
            },
            {"team": {"name": "Nicolas Mejia"}, "long": False},
        ]
    }

    assert _live_market_side(market, "Alex Smith", "Andrew Smith") is None


def test_ambiguous_initial_and_surname_names_are_rejected() -> None:
    market = {
        "marketSides": [
            {"team": {"name": "Alex Smith"}, "long": True},
            {"team": {"name": "Andrew Smith"}, "long": False},
        ]
    }

    assert _live_market_side(market, "A. Smith", "Andrew Smith") is None
    assert not PolymarketExecutionEngine._market_names_match(
        market, "A. Smith", "Andrew Smith"
    )


def test_live_side_overrides_conflicting_discovery_side() -> None:
    market_sides = [
        {"team": {"name": "Alex Hernandez"}, "long": False},
        {"team": {"name": "Nicolas Mejia"}, "long": True},
    ]
    client = FakeClient(markets=FakeMarkets(market_sides=market_sides))
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record(side=LONG_SIDE))

    assert result.status == "EXECUTED"
    assert result.market_side == SHORT_SIDE
    assert client.orders.create_calls[0]["intent"] == "ORDER_INTENT_BUY_SHORT"


def test_open_position_blocks_new_order() -> None:
    client = FakeClient(
        portfolio=FakePortfolio(
            {
                "other-market": {
                    "netPosition": "1.5",
                    "expired": False,
                }
            }
        )
    )
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record())

    assert result.status == "REJECTED"
    assert "position is already open" in result.reason
    assert client.orders.create_calls == []


def test_open_order_blocks_new_order() -> None:
    orders = FakeOrders(open_orders=[{"id": "existing"}])
    client = FakeClient(orders=orders)
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record())

    assert result.status == "REJECTED"
    assert "order is already open" in result.reason
    assert orders.create_calls == []


def test_suspended_market_is_rejected_before_preview() -> None:
    client = FakeClient(markets=FakeMarkets(state="MARKET_STATE_SUSPENDED"))
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record())

    assert result.status == "REJECTED"
    assert "suspended" in result.reason
    assert client.orders.preview_calls == []


def test_price_below_sanity_floor_is_rejected() -> None:
    client = FakeClient(markets=FakeMarkets(ask=0.35))
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record())

    assert result.status == "REJECTED"
    assert "outside the configured execution range" in result.reason
    assert client.orders.create_calls == []


def test_order_cap_rejects_instead_of_silently_reducing_ten_percent() -> None:
    client = FakeClient(account=FakeAccount(balance=500.0, buying_power=500.0))
    engine = PolymarketExecutionEngine(config(maximum_order_usd=25.0), client=client)

    result = engine.execute_trade(record())

    assert result.status == "REJECTED"
    assert result.stake_amount == 50.0
    assert "exceeds the configured order cap" in result.reason
    assert client.orders.create_calls == []


def test_exchange_rejection_is_not_reported_as_filled() -> None:
    client = FakeClient(orders=FakeOrders(rejected=True))
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record())

    assert result.status == "REJECTED"
    assert result.order_id == "rejected-1"
    assert result.reason == "NO_LIQUIDITY"


class FakeExecutionEngine:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def signal_key(payload: dict[str, Any]) -> str:
        return str(payload["trade_key"])

    def execute_trade(self, payload: dict[str, Any]) -> ExecutionResult:
        self.calls.append(payload)
        return ExecutionResult(
            status="EXECUTED",
            reason="Order filled.",
            signal_key=str(payload["trade_key"]),
            player=str(payload["player"]),
            opponent=str(payload["opponent"]),
            market_slug=str(payload["market_slug"]),
            market_side=str(payload["market_side"]),
            account_balance=8.0,
            buying_power=8.0,
            stake_amount=0.80,
            player_price_cents=68.0,
            order_id="order-1",
            order_state="ORDER_STATE_FILLED",
        )


def test_worker_forwards_each_trade_signal_to_executor_once() -> None:
    worker = RailwayShadowWorker(
        WorkerConfig(
            api_tennis_key="test",
            supabase_url="",
            supabase_key="",
            dry_run=True,
            worker_id="test-worker",
        )
    )
    fake = FakeExecutionEngine()
    worker.execution_engine = fake
    report = CycleReport(cycle_id="cycle", started_at="2026-07-25T00:00:00Z")
    payload = record()

    worker._queue_execution_signals([payload, payload])
    worker._flush_execution_signals(report)
    worker._queue_execution_signals([payload])
    worker._flush_execution_signals(report)

    assert len(fake.calls) == 1
    assert report.execution_attempts == 1
    assert report.execution_orders == 1
