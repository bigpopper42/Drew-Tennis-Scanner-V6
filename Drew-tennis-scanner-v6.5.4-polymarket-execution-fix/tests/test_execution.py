from __future__ import annotations

from typing import Any

from scanner.execution import (
    ExecutionConfig,
    ExecutionResult,
    LONG_SIDE,
    SHORT_SIDE,
    PolymarketExecutionEngine,
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
        state: str | None = "MARKET_STATE_OPEN",
        bid: float = 0.32,
        ask: float = 0.68,
        slug: str = "aec-atp-hernandez-mejia-2026-07-25",
        title: str = "Alex Hernandez vs Nicolas Mejia",
        description: str = "Who will win?",
        market_sides: list[dict[str, Any]] | None = None,
        nested_book: bool = True,
        wrapped_market: bool = True,
    ) -> None:
        sides = market_sides
        if sides is None:
            sides = [
                {"long": True, "team": {"name": "Alex Hernandez"}},
                {"long": False, "team": {"name": "Nicolas Mejia"}},
            ]
        market = {
            "slug": slug,
            "title": title,
            "description": description,
            "active": active,
            "closed": closed,
            "marketSides": sides,
        }
        self.market_payload = {"market": market} if wrapped_market else market
        market_data: dict[str, Any] = {
            "marketSlug": slug,
            "bids": [{"px": {"value": str(bid), "currency": "USD"}, "qty": "10"}],
            "offers": [{"px": {"value": str(ask), "currency": "USD"}, "qty": "10"}],
        }
        if state is not None:
            market_data["state"] = state
        self.book_payload = {"marketData": market_data} if nested_book else market_data

    def retrieve_by_slug(self, _slug: str) -> dict[str, Any]:
        return self.market_payload

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


def record(
    *,
    side: str | None = LONG_SIDE,
    player: str = "Alex Hernandez",
    opponent: str = "Nicolas Mejia",
    slug: str = "aec-atp-hernandez-mejia-2026-07-25",
) -> dict[str, Any]:
    return {
        "decision_status": "TRADE",
        "alert_eligible": True,
        "trade_key": f"event-1|{player.casefold()}",
        "event_key": "event-1",
        "player": player,
        "opponent": opponent,
        "market_found": True,
        "market_slug": slug,
        "market_side": side,
        "market_match_confidence": 95.0,
    }


def test_live_long_order_uses_documented_nested_book_and_ten_percent_cash() -> None:
    client = FakeClient()
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record())

    assert result.status == "EXECUTED"
    assert result.stake_amount == 0.80
    assert result.player_price_cents == 68.0
    assert result.market_side == LONG_SIDE
    request = client.orders.create_calls[0]
    assert request["cashOrderQty"]["value"] == "0.80"
    assert request["intent"] == "ORDER_INTENT_BUY_LONG"
    assert request["manualOrderIndicator"] == "MANUAL_ORDER_INDICATOR_AUTOMATIC"
    assert request["tif"] == "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL"
    assert len(client.orders.preview_calls) == 1


def test_missing_discovery_side_continues_when_live_market_maps_player() -> None:
    client = FakeClient()
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record(side=None))

    assert result.status == "EXECUTED"
    assert result.market_side == LONG_SIDE
    assert client.orders.create_calls[0]["intent"] == "ORDER_INTENT_BUY_LONG"


def test_generic_title_validates_from_monteiro_and_mazza_market_sides() -> None:
    slug = "aec-atp-thimon-matmaz-2026-07-27"
    markets = FakeMarkets(
        slug=slug,
        title="ATP tennis match winner",
        description="Match winner market",
        ask=0.99,
        bid=0.01,
        market_sides=[
            {
                "long": True,
                "team": {
                    "name": "Thiago Monteiro",
                    "displayName": "Thiago Monteiro",
                    "abbreviation": "T. Monteiro",
                },
            },
            {
                "long": False,
                "team": {
                    "name": "Matteo Mazza",
                    "safeName": "Matteo Mazza",
                    "alias": "M. Mazza",
                },
            },
        ],
    )
    client = FakeClient(markets=markets)
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(
        record(side=None, player="T. Monteiro", opponent="M. Mazza", slug=slug)
    )

    assert result.status == "EXECUTED"
    assert result.market_side == LONG_SIDE
    assert result.player_price_cents == 99.0


def test_live_market_overwrites_wrong_discovery_side_with_short_side() -> None:
    client = FakeClient()
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(
        record(side=LONG_SIDE, player="N. Mejia", opponent="A. Hernandez")
    )

    assert result.status == "EXECUTED"
    assert result.market_side == SHORT_SIDE
    assert result.player_price_cents == 68.0
    request = client.orders.create_calls[0]
    assert request["intent"] == "ORDER_INTENT_BUY_SHORT"
    assert request["slippageTolerance"]["currentPrice"]["value"] == "0.32"


def test_initials_and_full_names_map_safely_when_surnames_agree() -> None:
    market = {
        "marketSides": [
            {"long": True, "team": {"name": "Alejandro Tabilo"}},
            {"long": False, "team": {"name": "Tallon Griekspoor"}},
        ]
    }

    assert (
        PolymarketExecutionEngine._live_market_side(
            market, "A. Tabilo", "T. Griekspoor"
        )
        == LONG_SIDE
    )
    assert PolymarketExecutionEngine._market_names_match(
        market, "A. Tabilo", "T. Griekspoor"
    )


def test_competitors_cannot_map_to_the_same_market_side() -> None:
    market = {
        "marketSides": [
            {
                "long": True,
                "team": {
                    "name": "Thiago Monteiro",
                    "alias": "Matteo Mazza",
                },
            },
            {"long": False, "team": {"name": "Unrelated Player"}},
        ]
    }

    assert (
        PolymarketExecutionEngine._live_market_side(
            market, "T. Monteiro", "M. Mazza"
        )
        is None
    )
    assert not PolymarketExecutionEngine._market_names_match(
        market, "T. Monteiro", "M. Mazza"
    )


def test_ambiguous_structured_names_remain_rejected() -> None:
    markets = FakeMarkets(
        title="Generic tennis market",
        market_sides=[
            {"long": True, "team": {"name": "A. Smith"}},
            {"long": False, "team": {"name": "A. Smith"}},
        ],
    )
    client = FakeClient(markets=markets)
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(
        record(side=None, player="Alex Smith", opponent="Adam Smith")
    )

    assert result.status == "REJECTED"
    assert result.reason == "Live market names do not match the scanner signal."
    assert client.orders.preview_calls == []
    assert client.orders.create_calls == []


def test_flat_book_shape_remains_compatible_without_false_suspension() -> None:
    client = FakeClient(markets=FakeMarkets(nested_book=False))
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record())

    assert result.status == "EXECUTED"
    assert client.orders.create_calls



def test_documented_market_data_is_authoritative_over_top_level_state() -> None:
    markets = FakeMarkets(state="MARKET_STATE_OPEN")
    markets.book_payload["state"] = "MARKET_STATE_SUSPENDED"
    client = FakeClient(markets=markets)
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record())

    assert result.status == "EXECUTED"
    assert client.orders.create_calls


def test_direct_authenticated_market_payload_is_supported() -> None:
    client = FakeClient(markets=FakeMarkets(wrapped_market=False))
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record(side=None))

    assert result.status == "EXECUTED"
    assert result.market_side == LONG_SIDE


def test_suspended_market_reports_actual_state_before_preview() -> None:
    client = FakeClient(markets=FakeMarkets(state="MARKET_STATE_SUSPENDED"))
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record())

    assert result.status == "REJECTED"
    assert result.reason == (
        "Polymarket order book is not open "
        "(reported state: MARKET_STATE_SUSPENDED)."
    )
    assert client.orders.preview_calls == []


def test_missing_book_state_is_not_mislabeled_as_suspended() -> None:
    client = FakeClient(markets=FakeMarkets(state=None))
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record())

    assert result.status == "REJECTED"
    assert result.reason == (
        "Polymarket order-book state was missing from the API response."
    )
    assert "suspended" not in result.reason.casefold()
    assert client.orders.preview_calls == []


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
