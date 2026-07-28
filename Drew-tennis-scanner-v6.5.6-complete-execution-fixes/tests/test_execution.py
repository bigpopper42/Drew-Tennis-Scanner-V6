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
        question: str | None = None,
        sports_market_type_v2: str | None = "SPORTS_MARKET_TYPE_MONEYLINE",
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
            "question": question or title,
            "description": description,
            "active": active,
            "closed": closed,
            "marketSides": sides,
        }
        if sports_market_type_v2 is not None:
            market["sportsMarketTypeV2"] = sports_market_type_v2
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
        create_response: dict[str, Any] | None = None,
        retrieve_responses: list[dict[str, Any]] | None = None,
        retrieve_error: Exception | None = None,
    ) -> None:
        self.open_orders = open_orders or []
        self.rejected = rejected
        self.create_response = create_response
        self.retrieve_responses = list(retrieve_responses or [])
        self.retrieve_error = retrieve_error
        self.preview_calls: list[dict[str, Any]] = []
        self.create_calls: list[dict[str, Any]] = []
        self.list_calls: list[dict[str, Any] | None] = []
        self.retrieve_calls: list[str] = []
        self.last_created: dict[str, Any] = {}

    def list(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.list_calls.append(params)
        return {"orders": self.open_orders}

    def preview(self, params: dict[str, Any]) -> dict[str, Any]:
        self.preview_calls.append(params)
        request = params.get("request", params)
        return {"order": request}

    def create(self, params: dict[str, Any]) -> dict[str, Any]:
        self.create_calls.append(params)
        if self.create_response is not None:
            self.last_created = self.create_response
            return self.create_response
        if self.rejected:
            self.last_created = {
                "id": "rejected-1",
                "executions": [
                    {
                        "type": "EXECUTION_TYPE_REJECTED",
                        "orderRejectReason": "NO_LIQUIDITY",
                        "order": {"id": "rejected-1", "state": "ORDER_STATE_REJECTED"},
                    }
                ],
            }
            return self.last_created
        self.last_created = {
            "id": "order-1",
            "executions": [
                {
                    "type": "EXECUTION_TYPE_FILL",
                    "order": {
                        "id": "order-1",
                        "state": "ORDER_STATE_FILLED",
                        "cumQuantity": "2.35",
                    },
                }
            ],
        }
        return self.last_created

    def retrieve(self, order_id: str) -> dict[str, Any]:
        self.retrieve_calls.append(order_id)
        if self.retrieve_error is not None:
            raise self.retrieve_error
        if self.retrieve_responses:
            return self.retrieve_responses.pop(0)
        return self.last_created


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
        "bankroll_pct": 20.0,
        "minimum_order_usd": 0.50,
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
        "recommendation_change": "INITIAL",
        "stake_pct": 5.0,
    }


def test_live_long_order_uses_documented_nested_book_and_twenty_percent_cash() -> None:
    client = FakeClient()
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record())

    assert result.status == "EXECUTED"
    assert result.stake_amount == 1.60
    assert result.player_price_cents == 68.0
    assert result.market_side == LONG_SIDE
    request = client.orders.create_calls[0]
    assert request["cashOrderQty"]["value"] == "1.60"
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


def test_authenticated_side_mapping_accepts_boolean_strings_and_reversed_names() -> None:
    slug = "aec-atp-tab-gri-2026-07-28"
    markets = FakeMarkets(
        slug=slug,
        title="ATP tennis match winner",
        market_sides=[
            {"long": "true", "team": {"name": "Tabilo, Alejandro"}},
            {"long": "false", "team": {"name": "Griekspoor, Tallon"}},
        ],
    )
    client = FakeClient(markets=markets)
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(
        record(side=None, player="A. Tabilo", opponent="T. Griekspoor", slug=slug)
    )

    assert result.status == "EXECUTED"
    assert result.market_side == LONG_SIDE


def test_authenticated_side_mapping_accepts_yes_no_outcome_flags() -> None:
    slug = "aec-atp-tab-gri-2026-07-28"
    markets = FakeMarkets(
        slug=slug,
        title="ATP tennis match winner",
        market_sides=[
            {"outcome": "YES", "team": {"name": "Alejandro Tabilo"}},
            {"outcome": "NO", "team": {"name": "Tallon Griekspoor"}},
        ],
    )
    client = FakeClient(markets=markets)
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(
        record(side=None, player="A. Tabilo", opponent="T. Griekspoor", slug=slug)
    )

    assert result.status == "EXECUTED"
    assert result.market_side == LONG_SIDE


def test_authenticated_side_mapping_rejects_stale_discovery_side_without_live_assignment() -> None:
    markets = FakeMarkets(
        title="Alex Hernandez vs Nicolas Mejia",
        market_sides=[
            {"name": "YES"},
            {"name": "NO"},
        ],
    )
    client = FakeClient(markets=markets)
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record(side=LONG_SIDE))

    assert result.status == "REJECTED"
    assert result.reason == "Backed player could not be mapped safely to YES or NO."
    assert client.orders.create_calls == []


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


def test_unrelated_open_position_does_not_block_new_market() -> None:
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

    assert result.status == "EXECUTED"
    assert client.orders.create_calls


def test_same_market_position_blocks_duplicate_order() -> None:
    slug = "aec-atp-hernandez-mejia-2026-07-25"
    client = FakeClient(
        portfolio=FakePortfolio(
            {slug: {"netPosition": "1.5", "expired": False}}
        )
    )
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record(slug=slug))

    assert result.status == "REJECTED"
    assert "same Polymarket market" in result.reason
    assert client.orders.create_calls == []


def test_same_market_position_allows_scanner_approved_upgrade() -> None:
    slug = "aec-atp-hernandez-mejia-2026-07-25"
    client = FakeClient(
        portfolio=FakePortfolio(
            {slug: {"netPosition": "1.5", "expired": False}}
        )
    )
    engine = PolymarketExecutionEngine(config(), client=client)
    payload = record(slug=slug)
    payload["recommendation_change"] = "UPGRADE"
    payload["stake_pct"] = 7.0

    result = engine.execute_trade(payload)

    assert result.status == "EXECUTED"
    assert result.recommendation_change == "UPGRADE"
    assert client.orders.create_calls


def test_unrelated_open_order_does_not_block_new_market() -> None:
    orders = FakeOrders(
        open_orders=[{"id": "existing", "marketSlug": "other-market"}]
    )
    client = FakeClient(orders=orders)
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record())

    assert result.status == "EXECUTED"
    assert orders.create_calls
    assert orders.list_calls == [
        {"slugs": ["aec-atp-hernandez-mejia-2026-07-25"]}
    ]


def test_same_market_open_order_blocks_duplicate_order() -> None:
    slug = "aec-atp-hernandez-mejia-2026-07-25"
    orders = FakeOrders(open_orders=[{"id": "existing", "marketSlug": slug}])
    client = FakeClient(orders=orders)
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record(slug=slug))

    assert result.status == "REJECTED"
    assert "same Polymarket market" in result.reason
    assert orders.create_calls == []


def test_authenticated_exact_score_market_is_rejected_before_preview() -> None:
    slug = "astatc-atp-matarn-lormus-2026-07-27-es-0-2"
    markets = FakeMarkets(
        slug=slug,
        title="Matteo Arnaldi vs Lorenzo Musetti",
        question="Musetti wins 2-0",
        sports_market_type_v2="SPORTS_MARKET_TYPE_PROP",
        market_sides=[
            {"long": True, "team": {"name": "Lorenzo Musetti"}},
            {"long": False, "team": {"name": "Matteo Arnaldi"}},
        ],
    )
    client = FakeClient(markets=markets)
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(
        record(
            side=LONG_SIDE,
            player="L. Musetti",
            opponent="M. Arnaldi",
            slug=slug,
        )
    )

    assert result.status == "REJECTED"
    assert result.reason == (
        "Authenticated Polymarket market is not the match-winner moneyline."
    )
    assert result.market_question == "Musetti wins 2-0"
    assert result.market_type == "SPORTS_MARKET_TYPE_PROP"
    assert client.orders.preview_calls == []
    assert client.orders.create_calls == []


def test_price_below_sanity_floor_is_rejected() -> None:
    client = FakeClient(markets=FakeMarkets(ask=0.35))
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record())

    assert result.status == "REJECTED"
    assert "outside the configured execution range" in result.reason
    assert client.orders.create_calls == []


def test_twenty_percent_has_no_fixed_dollar_cap() -> None:
    client = FakeClient(account=FakeAccount(balance=500.0, buying_power=500.0))
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record())

    assert result.status == "EXECUTED"
    assert result.stake_amount == 100.0
    assert client.orders.create_calls[0]["cashOrderQty"]["value"] == "100.00"


def test_exchange_rejection_is_not_reported_as_filled() -> None:
    client = FakeClient(orders=FakeOrders(rejected=True))
    engine = PolymarketExecutionEngine(config(), client=client)

    result = engine.execute_trade(record())

    assert result.status == "REJECTED"
    assert result.order_id == "rejected-1"
    assert result.reason == "NO_LIQUIDITY"


def test_bare_order_id_is_pending_not_reported_as_filled() -> None:
    orders = FakeOrders(
        create_response={"id": "pending-1"},
        retrieve_responses=[
            {"id": "pending-1", "state": "ORDER_STATE_PENDING_NEW"},
            {"id": "pending-1", "state": "ORDER_STATE_PENDING_NEW"},
            {"id": "pending-1", "state": "ORDER_STATE_PENDING_NEW"},
        ],
    )
    result = PolymarketExecutionEngine(config(), client=FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "PENDING"
    assert not result.order_created
    assert result.order_id == "pending-1"
    assert result.order_state == "ORDER_STATE_PENDING_NEW"


def test_retrieved_rejection_overrides_bare_create_id() -> None:
    orders = FakeOrders(
        create_response={"id": "reject-later"},
        retrieve_responses=[
            {
                "id": "reject-later",
                "state": "ORDER_STATE_REJECTED",
                "rejectReason": "NO_LIQUIDITY",
            }
        ],
    )
    result = PolymarketExecutionEngine(config(), client=FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "REJECTED"
    assert result.reason == "NO_LIQUIDITY"
    assert not result.order_created


def test_retrieved_fill_confirms_order() -> None:
    orders = FakeOrders(
        create_response={"id": "fill-later"},
        retrieve_responses=[
            {
                "id": "fill-later",
                "state": "ORDER_STATE_FILLED",
                "cumQuantity": "1.75",
            }
        ],
    )
    result = PolymarketExecutionEngine(config(), client=FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "EXECUTED"
    assert result.order_created
    assert result.filled_quantity == 1.75


def test_retrieve_failure_does_not_turn_bare_id_into_success() -> None:
    orders = FakeOrders(
        create_response={"id": "unknown-1"},
        retrieve_error=RuntimeError("temporary status endpoint failure"),
    )
    result = PolymarketExecutionEngine(config(), client=FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "PENDING"
    assert not result.order_created
    assert "could not be confirmed" in result.reason


def test_execution_signal_key_allows_distinct_upgrade_tiers() -> None:
    initial = record()
    upgrade = dict(initial)
    upgrade["recommendation_change"] = "UPGRADE"
    upgrade["stake_pct"] = 7.0
    later_upgrade = dict(upgrade)
    later_upgrade["stake_pct"] = 9.0

    initial_key = PolymarketExecutionEngine.signal_key(initial)
    upgrade_key = PolymarketExecutionEngine.signal_key(upgrade)
    later_upgrade_key = PolymarketExecutionEngine.signal_key(later_upgrade)

    assert initial_key != upgrade_key
    assert upgrade_key != later_upgrade_key
    assert upgrade_key == PolymarketExecutionEngine.signal_key(dict(upgrade))


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
            market_question="Alex Hernandez vs Nicolas Mejia",
            market_type="SPORTS_MARKET_TYPE_MONEYLINE",
            bankroll_pct=20.0,
            account_balance=8.0,
            buying_power=8.0,
            stake_amount=1.60,
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
