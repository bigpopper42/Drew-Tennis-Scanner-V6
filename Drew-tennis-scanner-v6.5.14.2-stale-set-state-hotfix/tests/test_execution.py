from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from scanner.execution import (
    ExecutionConfig,
    ExecutionResult,
    LONG_SIDE,
    SHORT_SIDE,
    PolymarketExecutionEngine,
)
from scanner.worker_runtime import CycleReport, RailwayShadowWorker, WorkerConfig


MONEYLINE_SLUG = "aec-atp-svajd-mensik-2026-07-27"
SPREAD_SLUG = "astatc-atp-svajd-mensik-2026-07-27-spread"
TOTAL_SLUG = "astatc-atp-svajd-mensik-2026-07-27-total"


def moneyline_market(
    *,
    slug: str = MONEYLINE_SLUG,
    player_one: str = "Trevor Svajda",
    player_two: str = "Jakub Mensik",
    market_type: str | None = "SPORTS_MARKET_TYPE_MONEYLINE",
    active: bool | None = True,
    closed: bool | None = False,
    minimum_qty: str | None = "0.01",
    tick: str | None = "0.01",
    sides: list[dict[str, Any]] | None = None,
    title: str | None = None,
    description: str = "Match winner",
    line: Any = None,
    game_id: int = 9001,
) -> dict[str, Any]:
    market: dict[str, Any] = {
        "slug": slug,
        "title": title or f"{player_one} vs. {player_two}",
        "question": title or f"Will {player_one} defeat {player_two}?",
        "description": description,
        "eventSlug": "atp-svajd-mensik-2026-07-27",
        "gameId": game_id,
        "marketSides": sides
        or [
            {"long": True, "team": {"name": player_one}},
            {"long": False, "team": {"name": player_two}},
        ],
    }
    if active is not None:
        market["active"] = active
    if closed is not None:
        market["closed"] = closed
    if market_type is not None:
        market["sportsMarketType"] = market_type
    if minimum_qty is not None:
        market["minimumTradeQty"] = minimum_qty
    if tick is not None:
        market["orderPriceMinTickSize"] = tick
    if line is not None:
        market["line"] = line
    return market


def prop_market(slug: str, market_type: str, title: str) -> dict[str, Any]:
    return moneyline_market(
        slug=slug,
        market_type=market_type,
        title=title,
        minimum_qty="0.01",
        tick="0.01",
    )


def tennis_event(
    *,
    slug: str = "atp-svajd-mensik-2026-07-27",
    title: str = "Trevor Svajda vs. Jakub Mensik",
    game_id: int = 9001,
    markets: list[dict[str, Any]] | None = None,
    start_time: str = "2026-07-27T23:00:00Z",
) -> dict[str, Any]:
    return {
        "id": game_id,
        "slug": slug,
        "title": title,
        "description": "ATP Washington",
        "startTime": start_time,
        "active": True,
        "closed": False,
        "gameId": game_id,
        "markets": markets
        or [
            {"slug": MONEYLINE_SLUG},
            {"slug": SPREAD_SLUG},
            {"slug": TOTAL_SLUG},
        ],
    }


class FakeAccount:
    def __init__(self, balance: float = 100.0, buying_power: float = 100.0) -> None:
        self.balance = balance
        self.buying_power = buying_power

    def balances(self) -> dict[str, Any]:
        return {
            "balances": [
                {
                    "currency": "USD",
                    "currentBalance": {"value": str(self.balance), "currency": "USD"},
                    "buyingPower": {"value": str(self.buying_power), "currency": "USD"},
                }
            ]
        }


class FakeEvents:
    def __init__(self, events: list[dict[str, Any]] | None = None, error: Exception | None = None) -> None:
        self.events = events or []
        self.error = error
        self.list_calls: list[dict[str, Any]] = []
        self.retrieve_slug_calls: list[str] = []
        self.retrieve_id_calls: list[int] = []

    def list(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = dict(params or {})
        self.list_calls.append(query)
        if self.error:
            raise self.error
        offset = int(query.get("offset") or 0)
        limit = int(query.get("limit") or 100)
        return {"events": deepcopy(self.events[offset : offset + limit])}

    def retrieve_by_slug(self, slug: str) -> dict[str, Any]:
        self.retrieve_slug_calls.append(slug)
        if self.error:
            raise self.error
        for event in self.events:
            if str(event.get("slug") or "") == slug:
                return {"event": deepcopy(event)}
        raise KeyError(slug)

    def retrieve(self, event_id: int) -> dict[str, Any]:
        self.retrieve_id_calls.append(event_id)
        if self.error:
            raise self.error
        for event in self.events:
            if int(event.get("id") or -1) == event_id:
                return {"event": deepcopy(event)}
        raise KeyError(event_id)


class FakeMarkets:
    def __init__(
        self,
        markets: dict[str, dict[str, Any]] | None = None,
        *,
        bid: str = "0.22",
        ask: str = "0.78",
        book_state: str | None = "MARKET_STATE_OPEN",
        nested_book: bool = False,
        list_error: Exception | None = None,
        retrieve_error: Exception | None = None,
    ) -> None:
        default_moneyline = moneyline_market()
        default_spread = prop_market(
            SPREAD_SLUG,
            "SPORTS_MARKET_TYPE_SPREAD",
            "Will Trevor Svajda cover -1.5 vs. Jakub Mensik?",
        )
        default_spread["line"] = -1.5
        default_total = prop_market(
            TOTAL_SLUG,
            "SPORTS_MARKET_TYPE_TOTAL",
            "Over 22.5 total games",
        )
        default_total["line"] = 22.5
        self.markets = markets or {
            MONEYLINE_SLUG: default_moneyline,
            SPREAD_SLUG: default_spread,
            TOTAL_SLUG: default_total,
        }
        self.bid = bid
        self.ask = ask
        self.book_state = book_state
        self.nested_book = nested_book
        self.list_error = list_error
        self.retrieve_error = retrieve_error
        self.list_calls: list[dict[str, Any]] = []
        self.retrieve_calls: list[str] = []
        self.book_calls: list[str] = []

    def list(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = dict(params or {})
        self.list_calls.append(query)
        if self.list_error:
            raise self.list_error
        slugs = list(self.markets)
        return {"markets": [{"slug": slug} for slug in slugs]}

    def retrieve_by_slug(self, slug: str) -> dict[str, Any]:
        self.retrieve_calls.append(slug)
        if self.retrieve_error:
            raise self.retrieve_error
        if slug not in self.markets:
            raise KeyError(slug)
        return {"market": deepcopy(self.markets[slug])}

    def book(self, slug: str) -> dict[str, Any]:
        self.book_calls.append(slug)
        payload: dict[str, Any] = {
            "marketSlug": slug,
            "bids": [{"px": {"value": self.bid, "currency": "USD"}, "qty": "50"}],
            "offers": [{"px": {"value": self.ask, "currency": "USD"}, "qty": "50"}],
        }
        if self.book_state is not None:
            payload["state"] = self.book_state
        return {"marketData": payload} if self.nested_book else payload


class FakeOrders:
    def __init__(
        self,
        *,
        open_orders: list[dict[str, Any]] | None = None,
        preview_response: dict[str, Any] | None = None,
        create_response: dict[str, Any] | None = None,
        retrieve_responses: list[dict[str, Any]] | None = None,
        retrieve_error: Exception | None = None,
    ) -> None:
        self.open_orders = open_orders or []
        self.preview_response = preview_response
        self.create_response = create_response
        self.retrieve_responses = list(retrieve_responses or [])
        self.retrieve_error = retrieve_error
        self.list_calls: list[dict[str, Any] | None] = []
        self.preview_calls: list[dict[str, Any]] = []
        self.create_calls: list[dict[str, Any]] = []
        self.retrieve_calls: list[str] = []
        self.close_position_calls: list[dict[str, Any]] = []

    def list(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.list_calls.append(params)
        return {"orders": deepcopy(self.open_orders)}

    def preview(self, params: dict[str, Any]) -> dict[str, Any]:
        self.preview_calls.append(deepcopy(params))
        if self.preview_response is not None:
            return deepcopy(self.preview_response)
        if "request" not in params:
            raise FakeAPIError("Request is required", status_code=400)
        request = params["request"]
        if request.get("type") == "ORDER_TYPE_MARKET" and "cashOrderQty" not in request:
            raise FakeAPIError("cash_order_qty is required for market order", status_code=400)
        return {"order": deepcopy(request)}

    def create(self, params: dict[str, Any]) -> dict[str, Any]:
        self.create_calls.append(deepcopy(params))
        if self.create_response is not None:
            return deepcopy(self.create_response)
        return {
            "id": "order-1",
            "executions": [
                {
                    "type": "EXECUTION_TYPE_FILL",
                    "order": {
                        "id": "order-1",
                        "marketSlug": params["marketSlug"],
                        "intent": params.get("intent"),
                        "outcomeSide": params.get("outcomeSide"),
                        "action": params.get("action"),
                        "state": "ORDER_STATE_FILLED",
                        "cumQuantity": "25.64",
                    },
                }
            ],
        }

    def close_position(self, params: dict[str, Any]) -> dict[str, Any]:
        self.close_position_calls.append(deepcopy(params))
        return {
            "id": "stop-close-1",
            "executions": [
                {
                    "type": "EXECUTION_TYPE_FILL",
                    "order": {
                        "id": "stop-close-1",
                        "marketSlug": params["marketSlug"],
                        "state": "ORDER_STATE_FILLED",
                        "cumQuantity": "10",
                    },
                }
            ],
        }

    def retrieve(self, order_id: str) -> dict[str, Any]:
        self.retrieve_calls.append(order_id)
        if self.retrieve_error:
            raise self.retrieve_error
        if self.retrieve_responses:
            return deepcopy(self.retrieve_responses.pop(0))
        return {"order": {"id": order_id, "state": "ORDER_STATE_PENDING_NEW"}}


class FakePortfolio:
    def __init__(
        self,
        positions: dict[str, Any] | None = None,
        activities: list[dict[str, Any]] | None = None,
    ) -> None:
        self.payload = {"positions": positions or {}}
        self.activity_payload = {"activities": activities or [], "eof": True}
        self.calls: list[dict[str, Any] | None] = []
        self.activity_calls: list[dict[str, Any] | None] = []

    def positions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.calls.append(params)
        return deepcopy(self.payload)

    def activities(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.activity_calls.append(params)
        return deepcopy(self.activity_payload)


class FakeSearch:
    def __init__(self, events: list[dict[str, Any]] | None = None, error: Exception | None = None) -> None:
        self.events = events or []
        self.error = error
        self.calls: list[dict[str, Any]] = []

    def query(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        query = dict(params or {})
        self.calls.append(query)
        if self.error:
            raise self.error
        return {"events": deepcopy(self.events[: int(query.get("limit") or 50)])}


class FakeClient:
    def __init__(
        self,
        *,
        events: FakeEvents | None = None,
        markets: FakeMarkets | None = None,
        orders: FakeOrders | None = None,
        account: FakeAccount | None = None,
        portfolio: FakePortfolio | None = None,
        search: FakeSearch | None = None,
    ) -> None:
        self.events = events or FakeEvents([tennis_event()])
        self.markets = markets or FakeMarkets()
        self.orders = orders or FakeOrders()
        self.account = account or FakeAccount()
        self.portfolio = portfolio or FakePortfolio()
        self.search = search or FakeSearch()
        self.closed = False

    def close(self) -> None:
        self.closed = True


def config(**changes: Any) -> ExecutionConfig:
    values: dict[str, Any] = {
        "key_id": "key-id",
        "secret_key": "secret-key",
        "bankroll_pct": 20.0,
        "minimum_order_usd": 0.50,
        "minimum_price_cents": 50.0,
        "maximum_price_cents": 99.0,
        "slippage_ticks": 3,
        "event_page_size": 100,
        "event_page_limit": 2,
        "order_status_attempts": 2,
        "api_min_interval_seconds": 0.0,
        "rate_limit_backoff_seconds": 0.0,
        "minimum_market_confidence": 80.0,
    }
    values.update(changes)
    return ExecutionConfig(**values)


def record(
    *,
    player: str = "Jakub Mensik",
    opponent: str = "Trevor Svajda",
    slug: str = MONEYLINE_SLUG,
    event_date: str = "2026-07-27",
) -> dict[str, Any]:
    return {
        "decision_status": "TRADE",
        "alert_eligible": True,
        "trade_key": f"event-9001|{player.casefold()}",
        "event_key": "event-9001",
        "event_date": event_date,
        "event_time": "2026-07-27T23:00:00Z",
        "player": player,
        "opponent": opponent,
        "tournament": "ATP Washington",
        "market_found": bool(slug),
        "market_slug": slug,
        "market_side": LONG_SIDE,
        "market_match_confidence": 1.0,
        "recommendation_change": "INITIAL",
        "stake_pct": 20.0,
        "break_lead": 1,
        "backed_player_games_in_set": 5,
        "opponent_games_in_set": 3,
        "current_set_breaks_suffered": 0,
        "serving": True,
        "last_completed_game_was_break_by_backed": False,
        "current_service_game_reached_30_0": True,
        "current_service_game_reached_40_0": True,
    }


def engine(client: FakeClient, **config_changes: Any) -> PolymarketExecutionEngine:
    return PolymarketExecutionEngine(config(**config_changes), client=client)


def test_direct_moneyline_executes_exact_fifteen_percent_one_break_market_order_with_bounded_slippage() -> None:
    client = FakeClient()
    result = engine(client).execute_trade(record())

    assert result.status == "EXECUTED"
    assert result.stake_amount == 15.0
    assert result.market_side == SHORT_SIDE
    request = client.orders.create_calls[0]
    assert "price" not in request
    assert "quantity" not in request
    assert request["cashOrderQty"] == {"value": "15.00", "currency": "USD"}
    assert result.order_quantity == 18.51
    assert request["intent"] == "ORDER_INTENT_BUY_SHORT"
    assert request["outcomeSide"] == "OUTCOME_SIDE_NO"
    assert request["action"] == "ORDER_ACTION_BUY"
    assert request["type"] == "ORDER_TYPE_MARKET"
    assert request["tif"] == "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL"
    assert request["manualOrderIndicator"] == "MANUAL_ORDER_INDICATOR_AUTOMATIC"
    assert request["synchronousExecution"] is True
    assert request["slippageTolerance"] == {
        "currentPrice": {"value": "0.78", "currency": "USD"},
        "ticks": 3,
    }
    assert client.orders.preview_calls == [{"request": request}]


def test_short_market_order_uses_backed_outcome_reference_with_three_tick_slippage() -> None:
    client = FakeClient(markets=FakeMarkets(bid="0.22", ask="0.78"))
    result = engine(client).execute_trade(record())

    assert result.market_side == SHORT_SIDE
    assert result.player_price_cents == 78.0
    request = client.orders.create_calls[0]
    assert request["type"] == "ORDER_TYPE_MARKET"
    assert request["slippageTolerance"]["currentPrice"]["value"] == "0.78"
    assert request["slippageTolerance"]["ticks"] == 3
    assert request["cashOrderQty"] == {"value": "15.00", "currency": "USD"}
    assert result.order_quantity == 18.51


def test_short_76_cent_live_scenario_submits_cash_market_order_and_79_cent_cap() -> None:
    client = FakeClient(
        markets=FakeMarkets(bid="0.24", ask="0.76"),
        account=FakeAccount(balance=81.95, buying_power=81.95),
    )

    result = engine(client).execute_trade(record())

    assert result.status == "EXECUTED"
    assert result.market_side == SHORT_SIDE
    assert result.player_price_cents == 76.0
    assert result.stake_amount == 12.29
    assert result.maximum_player_price_cents == 79.0
    assert result.yes_reference_price_cents == 24.0
    assert result.best_yes_bid_cents == 24.0
    assert result.best_yes_offer_cents == 76.0
    request = client.orders.create_calls[0]
    assert request["intent"] == "ORDER_INTENT_BUY_SHORT"
    assert request["outcomeSide"] == "OUTCOME_SIDE_NO"
    assert request["action"] == "ORDER_ACTION_BUY"
    assert request["type"] == "ORDER_TYPE_MARKET"
    assert request["cashOrderQty"] == {"value": "12.29", "currency": "USD"}
    assert "quantity" not in request
    assert result.order_quantity == 15.55
    assert result.order_quantity * 0.79 <= 16.39
    assert request["slippageTolerance"] == {
        "currentPrice": {"value": "0.76", "currency": "USD"},
        "ticks": 3,
    }


def test_short_97_cent_live_scenario_uses_no_reference_and_clamps_to_99_cents() -> None:
    client = FakeClient(
        markets=FakeMarkets(bid="0.03", ask="0.04"),
        account=FakeAccount(balance=85.04, buying_power=85.04),
    )

    result = engine(client).execute_trade(record())

    assert result.status == "EXECUTED"
    assert result.market_side == SHORT_SIDE
    assert result.player_price_cents == 97.0
    assert result.stake_amount == 12.75
    assert result.maximum_player_price_cents == 99.0
    assert result.yes_reference_price_cents == 3.0
    request = client.orders.create_calls[0]
    assert request["intent"] == "ORDER_INTENT_BUY_SHORT"
    assert request["outcomeSide"] == "OUTCOME_SIDE_NO"
    assert request["cashOrderQty"] == {"value": "12.75", "currency": "USD"}
    assert request["slippageTolerance"] == {
        "currentPrice": {"value": "0.97", "currency": "USD"},
        "ticks": 2,
    }
    assert result.slippage_ticks == 2
    assert result.order_quantity == 12.87


def test_long_market_order_uses_best_offer_as_slippage_reference() -> None:
    client = FakeClient()
    result = engine(client).execute_trade(record(player="Trevor Svajda", opponent="Jakub Mensik"))

    assert result.market_side == LONG_SIDE
    assert result.player_price_cents == 78.0
    request = client.orders.create_calls[0]
    assert request["intent"] == "ORDER_INTENT_BUY_LONG"
    assert request["outcomeSide"] == "OUTCOME_SIDE_YES"
    assert request["action"] == "ORDER_ACTION_BUY"
    assert request["type"] == "ORDER_TYPE_MARKET"
    assert request["slippageTolerance"]["currentPrice"]["value"] == "0.78"
    assert request["slippageTolerance"]["ticks"] == 3
    assert request["cashOrderQty"] == {"value": "15.00", "currency": "USD"}
    assert result.order_quantity == 18.51


def test_scanner_side_and_confidence_never_override_authenticated_sides() -> None:
    payload = record()
    payload["market_side"] = LONG_SIDE
    payload["market_match_confidence"] = 0.0
    client = FakeClient()

    result = engine(client).execute_trade(payload)

    assert result.status == "EXECUTED"
    assert result.market_side == SHORT_SIDE


def test_event_first_recovery_finds_mensik_moneyline_without_scanning_unrelated_markets() -> None:
    client = FakeClient()
    result = engine(client).execute_trade(record(slug=""))

    assert result.status == "EXECUTED"
    assert result.market_slug == MONEYLINE_SLUG
    assert SPREAD_SLUG in client.markets.retrieve_calls
    assert TOTAL_SLUG in client.markets.retrieve_calls
    assert len(client.markets.retrieve_calls) == 3
    assert any(call.get("gameId") == 9001 for call in client.markets.list_calls)
    assert all("query" not in call for call in client.markets.list_calls)


def test_official_search_api_finds_exact_event_before_date_wide_listing() -> None:
    event = tennis_event()
    search = FakeSearch([event])
    events = FakeEvents([])
    client = FakeClient(search=search, events=events)

    result = engine(client).execute_trade(record(slug=""))

    assert result.status == "EXECUTED"
    assert search.calls[0] == {"query": "mensik svajda", "limit": 50, "page": 1}
    assert not events.list_calls


def test_bad_direct_event_hint_falls_back_to_exact_search_result() -> None:
    class BadHintEvents(FakeEvents):
        def retrieve_by_slug(self, slug: str) -> dict[str, Any]:
            self.retrieve_slug_calls.append(slug)
            raise FakeAPIError("invalid hint", 400)

    payload = record(slug="")
    payload["polymarket_event_slug"] = "bad-event-hint"
    search = FakeSearch([tennis_event()])
    client = FakeClient(events=BadHintEvents([]), search=search)

    result = engine(client).execute_trade(payload)

    assert result.status == "EXECUTED"
    assert search.calls


def test_exact_score_scanner_slug_is_rejected_then_event_moneyline_is_used() -> None:
    exact_slug = "astatc-atp-svajd-mensik-2026-07-27-es-2-0"
    markets = FakeMarkets(
        markets={
            exact_slug: prop_market(exact_slug, "SPORTS_MARKET_TYPE_PROP", "Jakub Mensik wins 2-0"),
            MONEYLINE_SLUG: moneyline_market(),
            SPREAD_SLUG: prop_market(SPREAD_SLUG, "SPORTS_MARKET_TYPE_SPREAD", "Svajda -1.5"),
        }
    )
    event = tennis_event(markets=[{"slug": exact_slug}, {"slug": MONEYLINE_SLUG}, {"slug": SPREAD_SLUG}])
    client = FakeClient(events=FakeEvents([event]), markets=markets)

    result = engine(client).execute_trade(record(slug=exact_slug))

    assert result.status == "EXECUTED"
    assert result.market_slug == MONEYLINE_SLUG
    assert markets.book_calls == [MONEYLINE_SLUG]


@pytest.mark.parametrize(
    ("player", "opponent", "event_title", "full_one", "full_two"),
    [
        ("A. Mannarino", "L. Tien", "Adrian Mannarino vs. Learner Tien", "Adrian Mannarino", "Learner Tien"),
        ("M. H. Rehberg", "S. Travaglia", "Max Hans Rehberg vs. Stefano Travaglia", "Max Hans Rehberg", "Stefano Travaglia"),
        ("T. Skatov", "T. Faurel", "Timofey Skatov vs. Thomas Faurel", "Timofey Skatov", "Thomas Faurel"),
        ("J. Mensik", "T. Svajda", "Jakub Mensik vs. Trevor Svajda", "Jakub Mensik", "Trevor Svajda"),
    ],
)
def test_abbreviated_scanner_names_match_full_event_and_side_names(
    player: str,
    opponent: str,
    event_title: str,
    full_one: str,
    full_two: str,
) -> None:
    slug = "aec-atp-name-case-2026-07-28"
    market = moneyline_market(slug=slug, player_one=full_one, player_two=full_two, game_id=42)
    event = tennis_event(
        slug="atp-name-case-2026-07-28",
        title=event_title,
        game_id=42,
        markets=[{"slug": slug}],
        start_time="2026-07-28T12:00:00Z",
    )
    client = FakeClient(events=FakeEvents([event]), markets=FakeMarkets(markets={slug: market}))

    result = engine(client).execute_trade(
        record(player=player, opponent=opponent, slug="", event_date="2026-07-28")
    )

    assert result.status == "EXECUTED"
    assert result.market_slug == slug


def test_unspecified_type_is_allowed_only_with_two_named_opposite_sides() -> None:
    slug = "aec-atp-generic-2026-07-28"
    market = moneyline_market(slug=slug, market_type=None, title="Who will win the game?")
    client = FakeClient(markets=FakeMarkets(markets={slug: market}))

    result = engine(client).execute_trade(record(slug=slug))

    assert result.status == "EXECUTED"


def test_outcome_flags_can_identify_long_and_short_contracts() -> None:
    sides = [
        {"outcome": "YES", "team": {"name": "Trevor Svajda"}},
        {"outcome": "NO", "team": {"name": "Jakub Mensik"}},
    ]
    market = moneyline_market(sides=sides)
    client = FakeClient(markets=FakeMarkets(markets={MONEYLINE_SLUG: market}))

    result = engine(client).execute_trade(record())

    assert result.status == "EXECUTED"
    assert result.market_side == SHORT_SIDE


def test_boolean_string_contract_flags_are_supported() -> None:
    sides = [
        {"long": "true", "team": {"name": "Trevor Svajda"}},
        {"long": "false", "team": {"name": "Jakub Mensik"}},
    ]
    market = moneyline_market(sides=sides)
    client = FakeClient(markets=FakeMarkets(markets={MONEYLINE_SLUG: market}))

    assert engine(client).execute_trade(record()).status == "EXECUTED"


@pytest.mark.parametrize(
    ("market_type", "title", "line"),
    [
        ("SPORTS_MARKET_TYPE_SPREAD", "Will Trevor Svajda cover -1.5?", -1.5),
        ("SPORTS_MARKET_TYPE_TOTAL", "Over 22.5 games", 22.5),
        ("SPORTS_MARKET_TYPE_PROP", "Jakub Mensik wins 2-0", None),
        (None, "Exact set score: Jakub Mensik wins 2-0", None),
        (None, "Will Jakub Mensik win the first set?", None),
    ],
)
def test_non_moneyline_markets_never_reach_preview(
    market_type: str | None,
    title: str,
    line: Any,
) -> None:
    market = moneyline_market(market_type=market_type, title=title, line=line)
    client = FakeClient(events=FakeEvents([]), markets=FakeMarkets(markets={MONEYLINE_SLUG: market}))

    result = engine(client).execute_trade(record())

    assert result.status in {"FAILED", "REJECTED"}
    assert not client.orders.preview_calls
    assert not client.orders.create_calls


def test_missing_both_structured_sides_is_rejected() -> None:
    market = moneyline_market(sides=[{"long": True, "team": {"name": "Jakub Mensik"}}])
    client = FakeClient(events=FakeEvents([]), markets=FakeMarkets(markets={MONEYLINE_SLUG: market}))

    result = engine(client).execute_trade(record())

    assert result.status in {"FAILED", "REJECTED"}
    assert not client.orders.create_calls


def test_same_player_cannot_map_to_both_sides() -> None:
    market = moneyline_market(
        sides=[
            {"long": True, "team": {"name": "Jakub Mensik"}},
            {"long": False, "team": {"name": "J. Mensik"}},
        ]
    )
    client = FakeClient(events=FakeEvents([]), markets=FakeMarkets(markets={MONEYLINE_SLUG: market}))

    result = engine(client).execute_trade(record())

    assert result.status in {"FAILED", "REJECTED"}
    assert not client.orders.create_calls


def test_no_matching_event_is_retryable_and_not_falsely_called_permanent() -> None:
    client = FakeClient(events=FakeEvents([]), markets=FakeMarkets(markets={}))
    result = engine(client).execute_trade(record(slug=""))

    assert result.status == "FAILED"
    assert result.retryable is True
    assert result.failure_stage == "event_discovery"
    assert "No active Polymarket tennis event" in result.reason


def test_event_api_failure_is_reported_with_exact_stage() -> None:
    client = FakeClient(events=FakeEvents(error=RuntimeError("429 rate limited")))
    result = engine(client).execute_trade(record(slug=""))

    assert result.status == "FAILED"
    assert result.retryable is True
    assert result.failure_stage == "event_discovery"
    assert "429 rate limited" in result.reason


def test_equally_matching_different_events_are_rejected_as_ambiguous() -> None:
    events = [
        tennis_event(game_id=1, slug="event-one"),
        tennis_event(game_id=2, slug="event-two"),
    ]
    client = FakeClient(events=FakeEvents(events))

    result = engine(client).execute_trade(record(slug=""))

    assert result.status == "REJECTED"
    assert result.failure_stage == "event_discovery"
    assert "More than one" in result.reason


def test_missing_market_minimum_quantity_or_tick_is_blocked() -> None:
    market = moneyline_market(minimum_qty=None, tick=None)
    client = FakeClient(markets=FakeMarkets(markets={MONEYLINE_SLUG: market}))

    result = engine(client).execute_trade(record())

    assert result.status == "REJECTED"
    assert result.failure_stage == "market_metadata"
    assert not client.orders.create_calls


def test_twenty_percent_below_market_minimum_quantity_retries_without_order() -> None:
    market = moneyline_market(minimum_qty="100")
    client = FakeClient(
        markets=FakeMarkets(markets={MONEYLINE_SLUG: market}),
        account=FakeAccount(balance=10.0, buying_power=10.0),
    )

    result = engine(client).execute_trade(record())

    assert result.status == "REJECTED"
    assert result.retryable is True
    assert result.failure_stage == "sizing"
    assert not client.orders.create_calls


def test_fifteen_percent_one_break_has_no_fixed_dollar_cap() -> None:
    client = FakeClient(account=FakeAccount(balance=1000.0, buying_power=1000.0))

    result = engine(client).execute_trade(record())

    assert result.status == "EXECUTED"
    assert result.stake_amount == 150.0
    request = client.orders.create_calls[0]
    assert request["cashOrderQty"] == {"value": "150.00", "currency": "USD"}
    assert "quantity" not in request
    assert result.order_quantity == 185.18
    assert result.order_quantity * 0.81 <= 200.0


def test_book_must_be_open() -> None:
    client = FakeClient(markets=FakeMarkets(book_state="MARKET_STATE_SUSPENDED"))
    result = engine(client).execute_trade(record())

    assert result.status == "FAILED"
    assert result.retryable is True
    assert result.failure_stage == "order_book"
    assert not client.orders.create_calls


def test_flat_and_nested_book_shapes_are_supported() -> None:
    flat = engine(FakeClient(markets=FakeMarkets(nested_book=False))).execute_trade(record())
    nested = engine(FakeClient(markets=FakeMarkets(nested_book=True))).execute_trade(record())

    assert flat.status == "EXECUTED"
    assert nested.status == "EXECUTED"


def test_missing_executable_side_liquidity_is_retryable() -> None:
    markets = FakeMarkets()
    original = markets.book

    def no_bid(slug: str) -> dict[str, Any]:
        payload = original(slug)
        payload["bids"] = []
        return payload

    markets.book = no_bid  # type: ignore[method-assign]
    client = FakeClient(markets=markets)

    result = engine(client).execute_trade(record())

    assert result.status == "FAILED"
    assert result.failure_stage == "order_book"
    assert not client.orders.create_calls


def test_live_price_outside_configured_range_is_retryable() -> None:
    client = FakeClient(markets=FakeMarkets(bid="0.05", ask="0.95"))
    result = engine(client, maximum_price_cents=90.0).execute_trade(record())

    assert result.status == "REJECTED"
    assert result.retryable is True
    assert result.failure_stage == "price"
    assert not client.orders.create_calls


def test_unrelated_position_does_not_block_a_distinct_market() -> None:
    portfolio = FakePortfolio(
        {"some-other-market": {"netPosition": "10", "marketMetadata": {"slug": "some-other-market"}}}
    )
    client = FakeClient(portfolio=portfolio)

    assert engine(client).execute_trade(record()).status == "EXECUTED"


def test_existing_same_market_one_break_position_blocks_duplicate_order() -> None:
    portfolio = FakePortfolio(
        {MONEYLINE_SLUG: {"netPositionDecimal": "-10", "cost": {"value": "15.00", "currency": "USD"}, "marketMetadata": {"slug": MONEYLINE_SLUG}}}
    )
    client = FakeClient(portfolio=portfolio)

    result = engine(client).execute_trade(record())

    assert result.status == "REJECTED"
    assert result.failure_stage == "target_exposure"
    assert "one-break target position already exists" in result.reason
    assert not client.orders.create_calls


def test_decimal_position_blocks_duplicate_when_deprecated_integer_is_zero() -> None:
    portfolio = FakePortfolio(
        positions={
            MONEYLINE_SLUG: {
                "netPosition": "0",
                "netPositionDecimal": "0.50",
                "expired": False,
            }
        }
    )
    client = FakeClient(portfolio=portfolio)

    result = engine(client).execute_trade(record())

    assert result.status == "REJECTED"
    assert result.failure_stage == "idempotency"
    assert not client.orders.create_calls


def test_prior_trade_activity_blocks_restart_duplicate_before_position_is_visible() -> None:
    portfolio = FakePortfolio(
        activities=[
            {
                "type": "ACTIVITY_TYPE_TRADE",
                "trade": {
                    "id": "trade-1",
                    "marketSlug": MONEYLINE_SLUG,
                    "state": "TRADE_STATE_CLEARED",
                    "qty": "0",
                    "qtyDecimal": "0.75",
                },
            }
        ]
    )
    client = FakeClient(portfolio=portfolio)

    result = engine(client).execute_trade(record())

    assert result.status == "REJECTED"
    assert result.filled_quantity == 0.75
    assert not client.orders.create_calls
    assert portfolio.activity_calls[0]["marketSlug"] == MONEYLINE_SLUG


def test_busted_trade_activity_does_not_block_a_fresh_order() -> None:
    portfolio = FakePortfolio(
        activities=[
            {
                "type": "ACTIVITY_TYPE_TRADE",
                "trade": {
                    "marketSlug": MONEYLINE_SLUG,
                    "state": "TRADE_STATE_BUSTED",
                    "qtyDecimal": "1.25",
                },
            }
        ]
    )
    client = FakeClient(portfolio=portfolio)

    result = engine(client).execute_trade(record())

    assert result.status == "EXECUTED"
    assert client.orders.create_calls


def test_existing_filled_order_blocks_restart_duplicate_before_position_is_visible() -> None:
    orders = FakeOrders(
        open_orders=[
            {
                "id": "filled-before-position",
                "marketSlug": MONEYLINE_SLUG,
                "state": "ORDER_STATE_FILLED",
                "cumQuantity": "4.25",
            }
        ]
    )
    client = FakeClient(orders=orders, portfolio=FakePortfolio())

    result = engine(client).execute_trade(record())

    assert result.status == "REJECTED"
    assert result.failure_stage == "idempotency"
    assert result.order_id == "filled-before-position"
    assert not orders.create_calls


def test_zero_fill_canceled_order_does_not_block_fresh_trade() -> None:
    orders = FakeOrders(
        open_orders=[
            {
                "id": "old-zero-fill",
                "marketSlug": MONEYLINE_SLUG,
                "state": "ORDER_STATE_CANCELED",
                "cumQuantity": "0",
            }
        ]
    )

    result = engine(FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "EXECUTED"
    assert len(orders.create_calls) == 1


def test_existing_same_market_open_order_blocks_duplicate_and_preserves_order_id() -> None:
    orders = FakeOrders(
        open_orders=[
            {
                "id": "open-7",
                "marketSlug": MONEYLINE_SLUG,
                "state": "ORDER_STATE_PENDING_NEW",
            }
        ]
    )
    client = FakeClient(orders=orders)

    result = engine(client).execute_trade(record())

    assert result.status == "PENDING"
    assert result.order_id == "open-7"
    assert result.terminal is True
    assert not client.orders.create_calls


def test_short_no_expired_ioc_ignores_default_exchange_option_enum() -> None:
    orders = FakeOrders(
        create_response={
            "id": "BJ1MRKCF49NE",
            "executions": [
                {
                    "type": "EXECUTION_TYPE_EXPIRED",
                    "orderRejectReason": "ORD_REJECT_REASON_EXCHANGE_OPTION",
                    "order": {
                        "id": "BJ1MRKCF49NE",
                        "marketSlug": MONEYLINE_SLUG,
                        "intent": "ORDER_INTENT_BUY_SHORT",
                        "outcomeSide": "OUTCOME_SIDE_NO",
                        "action": "ORDER_ACTION_BUY",
                        "type": "ORDER_TYPE_MARKET",
                        "tif": "TIME_IN_FORCE_IMMEDIATE_OR_CANCEL",
                        "state": "ORDER_STATE_EXPIRED",
                        "cumQuantity": "0",
                    },
                }
            ],
        }
    )
    client = FakeClient(
        markets=FakeMarkets(bid="0.13", ask="0.87"),
        account=FakeAccount(balance=67.67, buying_power=67.67),
        orders=orders,
    )

    result = engine(client).execute_trade(record())

    assert result.status == "UNFILLED"
    assert result.order_id == "BJ1MRKCF49NE"
    assert result.order_state == "ORDER_STATE_EXPIRED"
    assert result.retryable is True
    assert "EXCHANGE_OPTION" not in result.reason
    assert "no position was opened" in result.reason.lower()
    request = orders.create_calls[0]
    assert request["intent"] == "ORDER_INTENT_BUY_SHORT"
    assert request["outcomeSide"] == "OUTCOME_SIDE_NO"
    assert request["action"] == "ORDER_ACTION_BUY"
    assert request["type"] == "ORDER_TYPE_MARKET"
    assert "price" not in request
    assert request["slippageTolerance"] == {
        "currentPrice": {"value": "0.87", "currency": "USD"},
        "ticks": 3,
    }
    assert request["cashOrderQty"] == {"value": "10.15", "currency": "USD"}
    assert "quantity" not in request
    assert result.order_quantity == 11.27
    assert result.order_quantity * 0.90 <= 13.53


def test_preview_uses_required_request_envelope() -> None:
    client = FakeClient()
    engine(client).execute_trade(record())

    assert set(client.orders.preview_calls[0]) == {"request"}
    assert client.orders.preview_calls[0]["request"] == client.orders.create_calls[0]


def test_market_preview_requires_cash_order_qty_and_preserves_live_telemetry() -> None:
    class MissingCashExecutor(PolymarketExecutionEngine):
        def _preview(self, order_request: dict[str, Any]) -> dict[str, Any]:
            broken = dict(order_request)
            broken.pop("cashOrderQty", None)
            return super()._preview(broken)

    client = FakeClient(
        markets=FakeMarkets(bid="0.96", ask="0.97"),
        account=FakeAccount(balance=85.03, buying_power=85.03),
    )
    result = MissingCashExecutor(config(), client=client).execute_trade(
        record(player="Trevor Svajda", opponent="Jakub Mensik")
    )

    assert result.status == "REJECTED"
    assert result.failure_stage == "preview"
    assert "cash_order_qty is required for market order" in result.reason
    assert result.player_price_cents == 97.0
    assert result.best_yes_bid_cents == 96.0
    assert result.best_yes_offer_cents == 97.0
    assert result.stake_amount == 12.75
    assert result.order_quantity == 12.87


def test_preview_rejection_never_creates_order() -> None:
    orders = FakeOrders(
        preview_response={
            "order": {
                "state": "ORDER_STATE_REJECTED",
                "orderRejectReason": "ORD_REJECT_REASON_NO_LIQUIDITY",
            }
        }
    )
    client = FakeClient(orders=orders)

    result = engine(client).execute_trade(record())

    assert result.status == "REJECTED"
    assert result.failure_stage == "preview"
    assert result.retryable is True
    assert result.terminal is False
    assert not orders.create_calls


def test_invalid_preview_rejection_is_terminal() -> None:
    orders = FakeOrders(
        preview_response={
            "order": {
                "state": "ORDER_STATE_REJECTED",
                "orderRejectReason": "ORD_REJECT_REASON_INVALID_PRICE_INCREMENT",
            }
        }
    )
    result = engine(FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "REJECTED"
    assert result.retryable is False
    assert result.terminal is True
    assert not orders.create_calls


def test_exchange_rejection_is_never_reported_as_fill() -> None:
    orders = FakeOrders(
        create_response={
            "id": "rejected-1",
            "executions": [
                {
                    "type": "EXECUTION_TYPE_REJECTED",
                    "orderRejectReason": "ORD_REJECT_REASON_NO_LIQUIDITY",
                    "order": {"id": "rejected-1", "state": "ORDER_STATE_REJECTED"},
                }
            ],
        }
    )
    result = engine(FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "REJECTED"
    assert result.order_created is False
    assert result.order_id == "rejected-1"
    assert result.retryable is True
    assert result.terminal is False


def test_partial_fill_followed_by_cancel_is_executed_and_never_retryable() -> None:
    orders = FakeOrders(
        create_response={
            "id": "partial-1",
            "executions": [
                {
                    "type": "EXECUTION_TYPE_FILL",
                    "lastShares": "2.25",
                    "order": {
                        "id": "partial-1",
                        "state": "ORDER_STATE_CANCELED",
                        "cumQuantity": "2.25",
                    },
                },
                {
                    "type": "EXECUTION_TYPE_CANCELED",
                    "order": {
                        "id": "partial-1",
                        "state": "ORDER_STATE_CANCELED",
                        "cumQuantity": "2.25",
                    },
                },
            ],
        }
    )

    result = engine(FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "EXECUTED"
    assert result.order_created is True
    assert result.filled_quantity == 2.25
    assert result.retryable is False
    assert result.terminal is True
    assert "partially filled" in result.reason.lower()


def test_partial_fill_followed_by_reject_is_executed_and_never_retryable() -> None:
    orders = FakeOrders(
        create_response={
            "id": "partial-reject-1",
            "executions": [
                {
                    "type": "EXECUTION_TYPE_PARTIAL_FILL",
                    "lastShares": "1.5",
                    "order": {
                        "id": "partial-reject-1",
                        "state": "ORDER_STATE_REJECTED",
                        "cumQuantity": "1.5",
                        "orderRejectReason": "ORD_REJECT_REASON_NO_LIQUIDITY",
                    },
                }
            ],
        }
    )

    result = engine(FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "EXECUTED"
    assert result.order_created is True
    assert result.filled_quantity == 1.5
    assert result.retryable is False
    assert result.terminal is True


def test_bare_order_id_is_retrieved_until_filled() -> None:
    orders = FakeOrders(
        create_response={"id": "fill-later"},
        retrieve_responses=[
            {"order": {"id": "fill-later", "state": "ORDER_STATE_PENDING_NEW"}},
            {"order": {"id": "fill-later", "state": "ORDER_STATE_FILLED", "cumQuantity": "3.5"}},
        ],
    )
    result = engine(FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "EXECUTED"
    assert result.order_id == "fill-later"
    assert result.filled_quantity == 3.5
    assert orders.retrieve_calls == ["fill-later", "fill-later"]


def test_bare_order_id_with_retrieve_failure_remains_pending_and_terminal() -> None:
    orders = FakeOrders(
        create_response={"id": "unknown-1"},
        retrieve_error=RuntimeError("temporary status endpoint failure"),
    )
    result = engine(FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "PENDING"
    assert result.order_id == "unknown-1"
    assert result.retryable is False
    assert result.terminal is True
    assert result.order_created is False


def test_canceled_ioc_without_fill_is_unfilled() -> None:
    orders = FakeOrders(
        create_response={
            "id": "cancel-1",
            "executions": [
                {
                    "type": "EXECUTION_TYPE_CANCELED",
                    "order": {"id": "cancel-1", "state": "ORDER_STATE_CANCELED", "cumQuantity": "0"},
                }
            ],
        }
    )
    result = engine(FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "UNFILLED"
    assert result.order_id == "cancel-1"
    assert result.retryable is True
    assert result.terminal is False


def test_signal_key_is_stable_across_upgrade_labels_to_prevent_stacking() -> None:
    initial = record()
    upgrade = dict(initial, recommendation_change="UPGRADE", stake_pct=99.0)

    assert PolymarketExecutionEngine.signal_key(initial) == PolymarketExecutionEngine.signal_key(upgrade)


class FakeExecutionEngine:
    def __init__(self, results: list[ExecutionResult]) -> None:
        self.results = list(results)
        self.calls: list[dict[str, Any]] = []

    @staticmethod
    def signal_key(payload: dict[str, Any]) -> str:
        return str(payload["trade_key"])

    def execute_trade(self, payload: dict[str, Any]) -> ExecutionResult:
        self.calls.append(payload)
        return self.results.pop(0)


def worker_result(*, status: str, retryable: bool, order_id: str = "") -> ExecutionResult:
    return ExecutionResult(
        status=status,
        reason="test",
        signal_key="event-9001|jakub mensik",
        player="Jakub Mensik",
        opponent="Trevor Svajda",
        market_slug=MONEYLINE_SLUG,
        market_side=SHORT_SIDE,
        order_id=order_id,
        retryable=retryable,
    )


def make_worker() -> RailwayShadowWorker:
    return RailwayShadowWorker(
        WorkerConfig(
            api_tennis_key="test",
            supabase_url="",
            supabase_key="",
            dry_run=True,
            worker_id="test-worker",
        )
    )


def test_worker_suppresses_terminal_signal_after_one_attempt() -> None:
    worker = make_worker()
    fake = FakeExecutionEngine([worker_result(status="EXECUTED", retryable=False, order_id="order-1")])
    worker.execution_engine = fake  # type: ignore[assignment]
    report = CycleReport(cycle_id="cycle", started_at="2026-07-28T00:00:00Z")
    payload = record()

    worker._queue_execution_signals([payload, payload])
    worker._flush_execution_signals(report)
    worker._queue_execution_signals([payload])
    worker._flush_execution_signals(report)

    assert len(fake.calls) == 1
    assert report.execution_attempts == 1
    assert report.execution_orders == 1


def test_worker_requeues_retryable_failure_from_fresh_unchanged_trade() -> None:
    worker = make_worker()
    fake = FakeExecutionEngine(
        [
            worker_result(status="FAILED", retryable=True),
            worker_result(status="EXECUTED", retryable=False, order_id="order-2"),
        ]
    )
    worker.execution_engine = fake  # type: ignore[assignment]
    report = CycleReport(cycle_id="cycle", started_at="2026-07-28T00:00:00Z")
    initial = record()

    worker._queue_execution_signals([initial])
    worker._flush_execution_signals(report)
    assert initial["trade_key"] not in worker.processed_execution_signals
    assert initial["trade_key"] in worker.pending_execution_signals

    # The next unchanged scanner snapshot is normally not alert-eligible.  It
    # must still authorize one retry because the setup remains a live TRADE.
    refreshed = dict(initial, alert_eligible=False, recommendation_change="UNCHANGED")
    worker._queue_execution_signals([refreshed])
    worker._flush_execution_signals(report)

    assert len(fake.calls) == 2
    assert fake.calls[1]["alert_eligible"] is True
    assert report.execution_attempts == 2
    assert report.execution_orders == 1
    assert report.execution_errors == 1
    assert initial["trade_key"] in worker.processed_execution_signals
    assert initial["trade_key"] not in worker.pending_execution_signals


def test_worker_does_not_retry_stale_signal_when_match_is_absent() -> None:
    worker = make_worker()
    fake = FakeExecutionEngine([worker_result(status="FAILED", retryable=True)])
    worker.execution_engine = fake  # type: ignore[assignment]
    report = CycleReport(cycle_id="cycle", started_at="2026-07-28T00:00:00Z")
    payload = record()

    worker._queue_execution_signals([payload])
    worker._flush_execution_signals(report)
    worker._queue_execution_signals([])
    worker._flush_execution_signals(report)

    assert len(fake.calls) == 1
    assert payload["trade_key"] in worker.pending_execution_signals


def test_worker_drops_retry_when_fresh_setup_no_longer_trades() -> None:
    worker = make_worker()
    fake = FakeExecutionEngine([worker_result(status="FAILED", retryable=True)])
    worker.execution_engine = fake  # type: ignore[assignment]
    report = CycleReport(cycle_id="cycle", started_at="2026-07-28T00:00:00Z")
    payload = record()

    worker._queue_execution_signals([payload])
    worker._flush_execution_signals(report)
    no_trade = dict(payload, decision_status="NO TRADE", alert_eligible=False)
    worker._queue_execution_signals([no_trade])
    worker._flush_execution_signals(report)

    assert len(fake.calls) == 1
    assert payload["trade_key"] not in worker.pending_execution_signals


def test_market_side_mapping_accepts_reversed_full_names() -> None:
    sides = [
        {"long": True, "team": {"name": "Svajda, Trevor"}},
        {"long": False, "team": {"name": "Mensik, Jakub"}},
    ]
    market = moneyline_market(sides=sides)
    client = FakeClient(markets=FakeMarkets(markets={MONEYLINE_SLUG: market}))

    result = engine(client).execute_trade(record())

    assert result.status == "EXECUTED"
    assert result.market_side == SHORT_SIDE


def test_missing_active_field_is_allowed_but_order_book_must_still_be_open() -> None:
    market = moneyline_market(active=None)
    client = FakeClient(markets=FakeMarkets(markets={MONEYLINE_SLUG: market}))

    assert engine(client).execute_trade(record()).status == "EXECUTED"


def test_transient_event_read_is_retried_before_failing_signal() -> None:
    class FlakyEvents(FakeEvents):
        def list(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
            if not self.list_calls:
                self.list_calls.append(dict(params or {}))
                raise RuntimeError("temporary 429")
            return super().list(params)

    client = FakeClient(events=FlakyEvents([tennis_event()]))
    result = engine(client, api_read_attempts=2).execute_trade(record(slug=""))

    assert result.status == "EXECUTED"
    assert len(client.events.list_calls) >= 2


def test_create_timeout_recovers_open_order_before_allowing_retry() -> None:
    class TimeoutThenOpenOrders(FakeOrders):
        def list(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
            self.list_calls.append(params)
            if len(self.list_calls) == 1:
                return {"orders": []}
            return {
                "orders": [
                    {
                        "id": "accepted-despite-timeout",
                        "marketSlug": MONEYLINE_SLUG,
                        "state": "ORDER_STATE_PENDING_NEW",
                    }
                ]
            }

        def create(self, params: dict[str, Any]) -> dict[str, Any]:
            self.create_calls.append(deepcopy(params))
            raise TimeoutError("connection closed after submit")

    orders = TimeoutThenOpenOrders()
    result = engine(FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "PENDING"
    assert result.order_id == "accepted-despite-timeout"
    assert result.retryable is False
    assert result.terminal is True


def test_create_timeout_recovers_filled_order_and_reports_execution() -> None:
    class TimeoutThenFilledOrders(FakeOrders):
        def list(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
            self.list_calls.append(params)
            if len(self.list_calls) == 1:
                return {"orders": []}
            return {
                "orders": [
                    {
                        "id": "filled-despite-timeout",
                        "marketSlug": MONEYLINE_SLUG,
                        "state": "ORDER_STATE_FILLED",
                        "cumQuantity": "3.5",
                    }
                ]
            }

        def create(self, params: dict[str, Any]) -> dict[str, Any]:
            self.create_calls.append(deepcopy(params))
            raise TimeoutError("connection closed after submit")

    result = engine(FakeClient(orders=TimeoutThenFilledOrders())).execute_trade(record())

    assert result.status == "EXECUTED"
    assert result.order_id == "filled-despite-timeout"
    assert result.filled_quantity == 3.5
    assert result.retryable is False


def test_create_timeout_recovers_trade_activity_before_position_is_visible() -> None:
    class DynamicPortfolio(FakePortfolio):
        def activities(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
            self.activity_calls.append(params)
            if len(self.activity_calls) == 1:
                return {"activities": [], "eof": True}
            return {
                "activities": [
                    {
                        "type": "ACTIVITY_TYPE_TRADE",
                        "trade": {
                            "marketSlug": MONEYLINE_SLUG,
                            "state": "TRADE_STATE_NEW",
                            "qtyDecimal": "2.75",
                        },
                    }
                ],
                "eof": True,
            }

    class TimeoutOrders(FakeOrders):
        def create(self, params: dict[str, Any]) -> dict[str, Any]:
            self.create_calls.append(deepcopy(params))
            raise TimeoutError("connection closed after submit")

    result = engine(
        FakeClient(orders=TimeoutOrders(), portfolio=DynamicPortfolio())
    ).execute_trade(record())

    assert result.status == "EXECUTED"
    assert result.filled_quantity == 2.75
    assert result.retryable is False


def test_create_timeout_recovers_new_position_before_allowing_retry() -> None:
    class DynamicPortfolio(FakePortfolio):
        def positions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
            self.calls.append(params)
            if len(self.calls) == 1:
                return {"positions": {}}
            return {"positions": {MONEYLINE_SLUG: {"netPosition": "1.25"}}}

    class TimeoutOrders(FakeOrders):
        def create(self, params: dict[str, Any]) -> dict[str, Any]:
            self.create_calls.append(deepcopy(params))
            raise TimeoutError("connection closed after submit")

    result = engine(
        FakeClient(orders=TimeoutOrders(), portfolio=DynamicPortfolio())
    ).execute_trade(record())

    assert result.status == "PENDING"
    assert result.retryable is False
    assert result.terminal is True
    assert "position appeared" in result.reason


def test_ambiguous_create_failure_without_visible_order_is_pending_and_not_retried() -> None:
    class FailedOrders(FakeOrders):
        def create(self, params: dict[str, Any]) -> dict[str, Any]:
            self.create_calls.append(deepcopy(params))
            raise ConnectionError("request never reached exchange")

    result = engine(FakeClient(orders=FailedOrders())).execute_trade(record())

    assert result.status == "PENDING"
    assert result.retryable is False
    assert result.failure_stage == "order_submission"
    assert result.terminal is True
    assert "automatic retry was suppressed" in result.reason



class FakeAPIError(RuntimeError):
    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def test_direct_slug_authentication_error_is_not_disguised_as_market_miss() -> None:
    markets = FakeMarkets(retrieve_error=FakeAPIError("invalid credentials", 401))
    result = engine(FakeClient(markets=markets), api_read_attempts=3).execute_trade(record())

    assert result.status == "REJECTED"
    assert result.retryable is False
    assert result.failure_stage == "market_resolution"
    assert len(markets.retrieve_calls) == 1
    assert "credentials" in result.reason


def test_read_authentication_error_is_terminal_and_not_retried() -> None:
    events = FakeEvents(error=FakeAPIError("invalid credentials", 401))
    result = engine(FakeClient(events=events), api_read_attempts=3).execute_trade(record(slug=""))

    assert result.status == "REJECTED"
    assert result.retryable is False
    assert result.failure_stage == "event_discovery"
    assert len(events.list_calls) == 1


def test_candidate_market_authentication_error_is_not_disguised_as_no_moneyline() -> None:
    markets = FakeMarkets(retrieve_error=FakeAPIError("invalid credentials", 401))
    result = engine(FakeClient(markets=markets), api_read_attempts=3).execute_trade(record(slug=""))

    assert result.status == "REJECTED"
    assert result.retryable is False
    assert result.failure_stage == "market_selection"
    assert len(markets.retrieve_calls) == 1
    assert "credentials" in result.reason
    assert "contained no active match-winner" not in result.reason


def test_definitive_create_bad_request_is_terminal_rejection() -> None:
    class BadRequestOrders(FakeOrders):
        def create(self, params: dict[str, Any]) -> dict[str, Any]:
            self.create_calls.append(deepcopy(params))
            raise FakeAPIError("invalid request", 400)

    result = engine(FakeClient(orders=BadRequestOrders())).execute_trade(record())

    assert result.status == "REJECTED"
    assert result.retryable is False
    assert result.failure_stage == "order_submission"
    assert result.terminal is True


def test_preview_without_order_object_blocks_live_submission() -> None:
    orders = FakeOrders(preview_response={"warnings": []})
    result = engine(FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "FAILED"
    assert result.retryable is True
    assert result.failure_stage == "preview"
    assert not orders.create_calls


def test_preview_wrong_slug_blocks_live_submission() -> None:
    orders = FakeOrders(
        preview_response={
            "order": {
                "marketSlug": "wrong-market",
                "intent": "ORDER_INTENT_BUY_SHORT",
                "state": "ORDER_STATE_PENDING_NEW",
            }
        }
    )
    result = engine(FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "REJECTED"
    assert result.failure_stage == "preview"
    assert result.retryable is False
    assert not orders.create_calls


def test_preview_wrong_intent_blocks_live_submission() -> None:
    orders = FakeOrders(
        preview_response={
            "order": {
                "marketSlug": MONEYLINE_SLUG,
                "intent": "ORDER_INTENT_BUY_LONG",
                "state": "ORDER_STATE_PENDING_NEW",
            }
        }
    )
    result = engine(FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "REJECTED"
    assert result.failure_stage == "preview"
    assert result.retryable is False
    assert not orders.create_calls


def test_preview_explicit_no_contract_without_legacy_intent_is_accepted() -> None:
    orders = FakeOrders(
        preview_response={
            "order": {
                "marketSlug": MONEYLINE_SLUG,
                "outcomeSide": "OUTCOME_SIDE_NO",
                "action": "ORDER_ACTION_BUY",
                "state": "ORDER_STATE_PENDING_NEW",
            }
        }
    )
    result = engine(FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "EXECUTED"
    assert orders.create_calls


def test_preview_wrong_explicit_outcome_blocks_live_submission() -> None:
    orders = FakeOrders(
        preview_response={
            "order": {
                "marketSlug": MONEYLINE_SLUG,
                "outcomeSide": "OUTCOME_SIDE_YES",
                "action": "ORDER_ACTION_BUY",
                "state": "ORDER_STATE_PENDING_NEW",
            }
        }
    )
    result = engine(FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "REJECTED"
    assert result.failure_stage == "preview"
    assert result.retryable is False
    assert not orders.create_calls


def test_preview_conflicting_intent_and_outcome_blocks_live_submission() -> None:
    orders = FakeOrders(
        preview_response={
            "order": {
                "marketSlug": MONEYLINE_SLUG,
                "intent": "ORDER_INTENT_BUY_LONG",
                "outcomeSide": "OUTCOME_SIDE_NO",
                "action": "ORDER_ACTION_BUY",
                "state": "ORDER_STATE_PENDING_NEW",
            }
        }
    )
    result = engine(FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "REJECTED"
    assert result.failure_stage == "preview"
    assert "conflicting" in result.reason.lower()
    assert not orders.create_calls


def test_created_order_wrong_explicit_outcome_is_not_reported_as_executed() -> None:
    orders = FakeOrders(
        create_response={
            "id": "wrong-side-1",
            "order": {
                "id": "wrong-side-1",
                "marketSlug": MONEYLINE_SLUG,
                "intent": "ORDER_INTENT_BUY_LONG",
                "outcomeSide": "OUTCOME_SIDE_YES",
                "action": "ORDER_ACTION_BUY",
                "state": "ORDER_STATE_FILLED",
                "cumQuantity": "10",
            },
        }
    )
    result = engine(FakeClient(orders=orders)).execute_trade(record())

    assert result.status == "REJECTED"
    assert result.failure_stage == "order_submission"
    assert "expected OUTCOME_SIDE_NO" in result.reason


def test_ambiguous_create_failure_with_failed_reconciliation_stays_pending() -> None:
    class ReconciliationFailureOrders(FakeOrders):
        def list(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
            self.list_calls.append(params)
            if len(self.list_calls) == 1:
                return {"orders": []}
            raise TimeoutError("orders endpoint unavailable")

        def create(self, params: dict[str, Any]) -> dict[str, Any]:
            self.create_calls.append(deepcopy(params))
            raise TimeoutError("submit response lost")

    class ReconciliationFailurePortfolio(FakePortfolio):
        def positions(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
            self.calls.append(params)
            if len(self.calls) == 1:
                return {"positions": {}}
            raise TimeoutError("positions endpoint unavailable")

        def activities(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
            self.activity_calls.append(params)
            if len(self.activity_calls) == 1:
                return {"activities": [], "eof": True}
            raise TimeoutError("activities endpoint unavailable")

    result = engine(
        FakeClient(
            orders=ReconciliationFailureOrders(),
            portfolio=ReconciliationFailurePortfolio(),
        ),
        api_read_attempts=1,
    ).execute_trade(record())

    assert result.status == "PENDING"
    assert result.retryable is False
    assert result.terminal is True
    assert "Reconciliation errors" in result.reason


def test_order_polling_error_is_reported_without_resubmission() -> None:
    orders = FakeOrders(
        create_response={"id": "pending-9", "order": {"id": "pending-9", "state": "ORDER_STATE_PENDING_NEW"}},
        retrieve_error=TimeoutError("status endpoint unavailable"),
    )
    result = engine(FakeClient(orders=orders), order_status_attempts=2).execute_trade(record())

    assert result.status == "PENDING"
    assert result.order_id == "pending-9"
    assert result.retryable is False
    assert result.terminal is True
    assert "final-state polling failed" in result.reason

def test_minimum_quantity_is_checked_at_adverse_slippage_price() -> None:
    market = moneyline_market(minimum_qty="2", tick="0.01")
    client = FakeClient(
        markets=FakeMarkets(
            markets={MONEYLINE_SLUG: market},
            bid="0.50",
            ask="0.50",
        ),
        account=FakeAccount(balance=5.0, buying_power=5.0),
    )

    result = engine(client, minimum_price_cents=1.0).execute_trade(record())

    assert result.status == "REJECTED"
    assert result.failure_stage == "sizing"
    assert not client.orders.create_calls


def test_order_request_uses_only_official_create_contract_fields() -> None:
    official_fields = {
        "marketSlug",
        "intent",
        "outcomeSide",
        "action",
        "type",
        "price",
        "quantity",
        "tif",
        "participateDontInitiate",
        "goodTillTime",
        "cashOrderQty",
        "manualOrderIndicator",
        "synchronousExecution",
        "maxBlockTime",
        "slippageTolerance",
    }
    client = FakeClient()
    engine(client).execute_trade(record())

    request = client.orders.create_calls[0]
    assert set(request).issubset(official_fields)
    assert {
        "marketSlug",
        "intent",
        "outcomeSide",
        "action",
        "type",
        "cashOrderQty",
        "tif",
        "slippageTolerance",
    }.issubset(request)
    assert "price" not in request
    assert "quantity" not in request


def test_event_and_market_queries_use_official_sdk_filter_fields() -> None:
    official_event_fields = {
        "orderBy",
        "orderDirection",
        "id",
        "slug",
        "archived",
        "active",
        "closed",
        "liquidityMin",
        "liquidityMax",
        "volumeMin",
        "volumeMax",
        "startDateMin",
        "startDateMax",
        "endDateMin",
        "endDateMax",
        "tagId",
        "tagSlug",
        "relatedTags",
        "featured",
        "seriesId",
        "eventDate",
        "eventWeek",
        "startTimeMin",
        "startTimeMax",
        "gameId",
        "ended",
        "categories",
        "limit",
        "offset",
    }
    official_market_fields = {
        "orderBy",
        "orderDirection",
        "id",
        "slug",
        "eventSlug",
        "archived",
        "active",
        "closed",
        "liquidityMin",
        "liquidityMax",
        "volumeMin",
        "volumeMax",
        "gameId",
        "categories",
        "limit",
        "offset",
    }
    client = FakeClient()
    result = engine(client).execute_trade(record(slug=""))

    assert result.status == "EXECUTED"
    assert client.events.list_calls
    assert all(set(call).issubset(official_event_fields) for call in client.events.list_calls)
    assert client.markets.list_calls
    assert all(set(call).issubset(official_market_fields) for call in client.markets.list_calls)


@pytest.mark.parametrize(
    "title",
    [
        "Jakub Mensik to win in straight sets",
        "Correct Match Score: Mensik 2-0",
        "Set Betting: Mensik 2-1",
        "First Set Winner",
        "Will there be a tie-break?",
        "Number of Sets: Over 2.5",
        "Jakub Mensik wins 2 sets to 0",
    ],
)
def test_no_type_prop_titles_are_never_accepted_as_moneyline(title: str) -> None:
    prop = moneyline_market(market_type=None, title=title, description="")
    client = FakeClient(
        markets=FakeMarkets(markets={MONEYLINE_SLUG: prop}),
        events=FakeEvents(events=[]),
    )

    result = engine(client).execute_trade(record())

    assert result.status in {"FAILED", "REJECTED"}
    assert not client.orders.create_calls


def test_invalid_direct_prop_uses_its_event_slug_hint_before_broad_search() -> None:
    exact_slug = "astatc-atp-svajd-mensik-2026-07-27-es-2-0"
    exact = prop_market(exact_slug, "SPORTS_MARKET_TYPE_PROP", "Jakub Mensik wins 2-0")
    exact["eventSlug"] = "atp-svajd-mensik-2026-07-27"
    markets = FakeMarkets(markets={exact_slug: exact, MONEYLINE_SLUG: moneyline_market()})
    events = FakeEvents(
        [
            tennis_event(
                markets=[{"slug": exact_slug}, {"slug": MONEYLINE_SLUG}],
            )
        ]
    )
    client = FakeClient(events=events, markets=markets)

    result = engine(client).execute_trade(record(slug=exact_slug))

    assert result.status == "EXECUTED"
    assert events.retrieve_slug_calls == ["atp-svajd-mensik-2026-07-27"]
    assert events.list_calls == []


def test_nested_event_market_slugs_remain_usable_when_market_list_endpoint_fails() -> None:
    markets = FakeMarkets(list_error=RuntimeError("temporary list failure"))
    client = FakeClient(events=FakeEvents([tennis_event()]), markets=markets)

    result = engine(client, api_read_attempts=1).execute_trade(record(slug=""))

    assert result.status == "EXECUTED"
    assert result.market_slug == MONEYLINE_SLUG


def test_game_id_hint_is_used_before_date_wide_event_queries() -> None:
    payload = record(slug="")
    payload["game_id"] = 9001
    client = FakeClient()

    result = engine(client).execute_trade(payload)

    assert result.status == "EXECUTED"
    assert client.events.list_calls[0]["gameId"] == 9001


def test_explicit_order_rate_limit_is_retryable_without_marking_pending() -> None:
    class RateLimitError(Exception):
        status_code = 429

    class RateLimitedOrders(FakeOrders):
        def create(self, params: dict[str, Any]) -> dict[str, Any]:
            self.create_calls.append(deepcopy(params))
            raise RateLimitError("too many requests")

    client = FakeClient(orders=RateLimitedOrders())
    result = engine(client).execute_trade(record())

    assert result.status == "FAILED"
    assert result.retryable is True
    assert result.failure_stage == "order_submission"
    assert "rate-limit" in result.reason.lower()


def test_search_and_portfolio_queries_use_official_sdk_fields() -> None:
    official_search_fields = {"query", "limit", "seriesIds", "status", "page"}
    official_position_fields = {"market", "limit", "cursor"}
    official_activity_fields = {"limit", "cursor", "marketSlug", "types", "sortOrder"}

    search = FakeSearch(events=[])
    portfolio = FakePortfolio()
    client = FakeClient(search=search, portfolio=portfolio)
    result = engine(client).execute_trade(record(slug=""))

    assert result.status == "EXECUTED"
    assert search.calls
    assert all(set(call).issubset(official_search_fields) for call in search.calls)
    assert portfolio.calls
    assert all(set(call or {}).issubset(official_position_fields) for call in portfolio.calls)
    assert portfolio.activity_calls
    assert all(set(call or {}).issubset(official_activity_fields) for call in portfolio.activity_calls)


def test_cloudflare_1015_open_order_lookup_retries_then_executes() -> None:
    cloudflare_html = (
        "<!doctype html><html><head><title>Access denied | api.polymarket.us "
        "used Cloudflare to restrict access</title></head>"
        "<body>Error 1015<script>errorCode: 1015</script></body></html>"
    )

    class Cloudflare403(RuntimeError):
        status_code = 403

    class FlakyOpenOrders(FakeOrders):
        def list(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
            self.list_calls.append(params)
            if len(self.list_calls) < 3:
                raise Cloudflare403(cloudflare_html)
            return {"orders": []}

    orders = FlakyOpenOrders()
    result = engine(
        FakeClient(orders=orders),
        api_read_attempts=3,
        api_min_interval_seconds=0.0,
        rate_limit_backoff_seconds=0.0,
    ).execute_trade(record())

    assert result.status == "EXECUTED"
    assert len(orders.list_calls) == 3
    assert len(orders.create_calls) == 1


def test_exhausted_cloudflare_1015_is_retryable_and_html_is_hidden() -> None:
    cloudflare_html = (
        "<!doctype html><html><title>Access denied | api.polymarket.us used "
        "Cloudflare to restrict access</title><body>Error 1015</body></html>"
    )

    class Cloudflare403(RuntimeError):
        status_code = 403

    class BlockedOpenOrders(FakeOrders):
        def list(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
            self.list_calls.append(params)
            raise Cloudflare403(cloudflare_html)

    orders = BlockedOpenOrders()
    result = engine(
        FakeClient(orders=orders),
        api_read_attempts=3,
        api_min_interval_seconds=0.0,
        rate_limit_backoff_seconds=0.0,
    ).execute_trade(record())

    assert result.status == "FAILED"
    assert result.retryable is True
    assert result.failure_stage == "idempotency"
    assert len(orders.list_calls) == 3
    assert orders.create_calls == []
    assert "1015/429" in result.reason
    assert "<!doctype" not in result.reason.casefold()
    assert "<html" not in result.reason.casefold()


def test_cloudflare_1015_order_create_retries_only_definite_edge_block() -> None:
    class Cloudflare403(RuntimeError):
        status_code = 403

    class FlakyCreateOrders(FakeOrders):
        def create(self, params: dict[str, Any]) -> dict[str, Any]:
            self.create_calls.append(deepcopy(params))
            if len(self.create_calls) == 1:
                raise Cloudflare403(
                    "<!doctype html><title>Access denied</title>"
                    "Cloudflare to restrict access Error 1015"
                )
            return {
                "id": "order-after-backoff",
                "executions": [
                    {
                        "type": "EXECUTION_TYPE_FILL",
                        "order": {
                            "id": "order-after-backoff",
                            "marketSlug": params["marketSlug"],
                            "state": "ORDER_STATE_FILLED",
                            "cumQuantity": "25.64",
                        },
                    }
                ],
            }

    orders = FlakyCreateOrders()
    result = engine(
        FakeClient(orders=orders),
        api_read_attempts=3,
        api_min_interval_seconds=0.0,
        rate_limit_backoff_seconds=0.0,
    ).execute_trade(record())

    assert result.status == "EXECUTED"
    assert len(orders.create_calls) == 2


def test_stop_loss_closes_long_at_exactly_thirty_cents_without_quantity() -> None:
    portfolio = FakePortfolio(
        {MONEYLINE_SLUG: {"netPositionDecimal": "10", "marketMetadata": {"slug": MONEYLINE_SLUG}}}
    )
    client = FakeClient(
        portfolio=portfolio,
        markets=FakeMarkets(bid="0.30", ask="0.31"),
    )

    results = engine(client, stop_loss_trigger_cents=30.0).monitor_stop_losses()

    assert len(results) == 1
    result = results[0]
    assert result.status == "EXITED"
    assert result.market_side == LONG_SIDE
    assert result.observed_price_cents == 30.0
    assert result.trigger_price_cents == 30.0
    request = client.orders.close_position_calls[0]
    assert request["marketSlug"] == MONEYLINE_SLUG
    assert "quantity" not in request
    assert "cashOrderQty" not in request
    assert request["manualOrderIndicator"] == "MANUAL_ORDER_INDICATOR_AUTOMATIC"
    assert request["slippageTolerance"] == {
        "currentPrice": {"value": "0.3", "currency": "USD"},
        "ticks": 3,
    }


def test_stop_loss_closes_short_when_executable_no_bid_reaches_thirty_cents() -> None:
    portfolio = FakePortfolio(
        {MONEYLINE_SLUG: {"netPosition": "-10", "marketMetadata": {"slug": MONEYLINE_SLUG}}}
    )
    # A 70c YES offer implies a 30c executable NO bid.
    client = FakeClient(
        portfolio=portfolio,
        markets=FakeMarkets(bid="0.69", ask="0.70"),
    )

    results = engine(client, stop_loss_trigger_cents=30.0).monitor_stop_losses()

    assert len(results) == 1
    result = results[0]
    assert result.status == "EXITED"
    assert result.market_side == SHORT_SIDE
    assert result.observed_price_cents == 30.0
    request = client.orders.close_position_calls[0]
    assert request["slippageTolerance"]["currentPrice"]["value"] == "0.3"
    assert "quantity" not in request


def test_stop_loss_does_not_trigger_above_thirty_cents() -> None:
    portfolio = FakePortfolio(
        {MONEYLINE_SLUG: {"netPositionDecimal": "-10", "cost": {"value": "15.00", "currency": "USD"}, "marketMetadata": {"slug": MONEYLINE_SLUG}}}
    )
    client = FakeClient(
        portfolio=portfolio,
        markets=FakeMarkets(bid="0.31", ask="0.32"),
    )

    results = engine(client, stop_loss_trigger_cents=30.0).monitor_stop_losses()

    assert results == []
    assert client.orders.close_position_calls == []


def test_stop_loss_ignores_non_atp_positions() -> None:
    other_slug = "politics-example-market-2026"
    portfolio = FakePortfolio(
        {other_slug: {"netPosition": "10", "marketMetadata": {"slug": other_slug}}}
    )
    markets = FakeMarkets(markets={other_slug: moneyline_market(slug=other_slug)}, bid="0.10", ask="0.11")
    client = FakeClient(portfolio=portfolio, markets=markets)

    results = engine(client, stop_loss_trigger_cents=30.0).monitor_stop_losses()

    assert results == []
    assert client.markets.book_calls == []
    assert client.orders.close_position_calls == []


def test_execution_safety_gate_blocks_one_break_trade_at_one_game_even_if_record_says_trade() -> None:
    client = FakeClient()
    payload = record()
    payload.update({
        "break_lead": 1,
        "backed_player_games_in_set": 1,
        "current_set_breaks_suffered": 0,
        "serving": True,
        "current_game_score": "40-0",
        "current_service_game_reached_40_0": True,
    })
    result = engine(client).execute_trade(payload)
    assert result.status == "REJECTED"
    assert result.failure_stage == "match_state_safety"
    assert "requires at least 4" in result.reason
    assert not client.orders.create_calls


def test_execution_safety_gate_blocks_fresh_break_at_four_before_40_love() -> None:
    client = FakeClient()
    payload = record()
    payload.update({
        "break_lead": 1,
        "backed_player_games_in_set": 4,
        "current_set_breaks_suffered": 0,
        "serving": True,
        "last_completed_game_was_break_by_backed": True,
        "current_service_game_reached_40_0": False,
    })
    result = engine(client).execute_trade(payload)
    assert result.status == "REJECTED"
    assert result.failure_stage == "match_state_safety"
    assert "40-0" in result.reason
    assert not client.orders.create_calls


def test_execution_safety_gate_blocks_fresh_break_at_five_before_30_love() -> None:
    client = FakeClient()
    payload = record()
    payload.update({
        "break_lead": 1,
        "backed_player_games_in_set": 5,
        "current_set_breaks_suffered": 0,
        "serving": True,
        "last_completed_game_was_break_by_backed": True,
        "current_service_game_reached_30_0": False,
    })
    result = engine(client).execute_trade(payload)
    assert result.status == "REJECTED"
    assert result.failure_stage == "match_state_safety"
    assert "30-0" in result.reason
    assert not client.orders.create_calls


def test_fresh_two_break_signal_targets_twenty_five_percent() -> None:
    client = FakeClient(account=FakeAccount(balance=100.0, buying_power=100.0))
    trade = record()
    trade["break_lead"] = 2

    result = engine(client).execute_trade(trade)

    assert result.status == "EXECUTED"
    assert result.target_exposure_pct == 25.0
    assert result.position_upgrade is False
    assert result.stake_amount == 25.0
    assert client.orders.create_calls[0]["cashOrderQty"] == {"value": "25.00", "currency": "USD"}


def test_two_break_upgrade_adds_only_difference_from_fifteen_to_twenty_five_percent() -> None:
    portfolio = FakePortfolio(
        {
            MONEYLINE_SLUG: {
                "netPositionDecimal": "-15.5",
                "cost": {"value": "15.00", "currency": "USD"},
                "cashValue": {"value": "15.35", "currency": "USD"},
                "marketMetadata": {"slug": MONEYLINE_SLUG},
            }
        }
    )
    client = FakeClient(
        account=FakeAccount(balance=85.0, buying_power=85.0),
        portfolio=portfolio,
    )
    trade = record()
    trade["break_lead"] = 2
    trade["recommendation_change"] = "UPGRADED"

    result = engine(client).execute_trade(trade)

    assert result.status == "EXECUTED"
    assert result.position_upgrade is True
    assert result.target_exposure_pct == 25.0
    assert result.account_balance == 100.0
    assert result.existing_exposure_amount == 15.0
    assert result.target_exposure_amount == 25.0
    assert result.stake_amount == 10.0
    assert client.orders.create_calls[0]["cashOrderQty"] == {"value": "10.00", "currency": "USD"}


def test_two_break_upgrade_from_legacy_twenty_percent_adds_only_five_percent() -> None:
    portfolio = FakePortfolio(
        {
            MONEYLINE_SLUG: {
                "netPositionDecimal": "-20.5",
                "cost": {"value": "20.00", "currency": "USD"},
                "marketMetadata": {"slug": MONEYLINE_SLUG},
            }
        }
    )
    client = FakeClient(account=FakeAccount(balance=80.0, buying_power=80.0), portfolio=portfolio)
    trade = record()
    trade["break_lead"] = 2

    result = engine(client).execute_trade(trade)

    assert result.status == "EXECUTED"
    assert result.existing_exposure_amount == 20.0
    assert result.target_exposure_amount == 25.0
    assert result.stake_amount == 5.0


def test_repeat_two_break_signal_does_not_stack_above_twenty_five_percent_target() -> None:
    portfolio = FakePortfolio(
        {
            MONEYLINE_SLUG: {
                "netPositionDecimal": "-25.5",
                "cost": {"value": "25.00", "currency": "USD"},
                "marketMetadata": {"slug": MONEYLINE_SLUG},
            }
        }
    )
    client = FakeClient(account=FakeAccount(balance=75.0, buying_power=75.0), portfolio=portfolio)
    trade = record()
    trade["break_lead"] = 2

    result = engine(client).execute_trade(trade)

    assert result.status == "REJECTED"
    assert result.failure_stage == "target_exposure"
    assert "already meets the 25% target" in result.reason
    assert client.orders.create_calls == []


def test_two_break_upgrade_refuses_opposite_side_position() -> None:
    portfolio = FakePortfolio(
        {
            MONEYLINE_SLUG: {
                "netPositionDecimal": "15.5",
                "cost": {"value": "15.00", "currency": "USD"},
                "marketMetadata": {"slug": MONEYLINE_SLUG},
            }
        }
    )
    client = FakeClient(account=FakeAccount(balance=85.0, buying_power=85.0), portfolio=portfolio)
    trade = record()
    trade["break_lead"] = 2

    result = engine(client).execute_trade(trade)

    assert result.status == "REJECTED"
    assert result.failure_stage == "idempotency"
    assert "opposite outcome" in result.reason
    assert client.orders.create_calls == []


def test_default_stop_loss_trigger_is_forty_cents() -> None:
    portfolio = FakePortfolio(
        {
            MONEYLINE_SLUG: {
                "netPositionDecimal": "10",
                "marketMetadata": {"slug": MONEYLINE_SLUG},
            }
        }
    )
    client = FakeClient(portfolio=portfolio, markets=FakeMarkets(bid="0.35", ask="0.36"))

    results = engine(client).monitor_stop_losses()

    assert len(results) == 1
    assert results[0].trigger_price_cents == 35.0
    assert results[0].observed_price_cents == 35.0
    assert len(client.orders.close_position_calls) == 1


def test_execution_safety_gate_blocks_impossible_closing_set_from_stale_prior_set() -> None:
    client = FakeClient()
    payload = record()
    payload.update({
        "break_lead": 2,
        "best_of_sets": 3,
        "current_set_number": 1,
        "completed_sets": 0,
        "match_closing_set": True,
        "serving_for_match": True,
        "backed_player_games_in_set": 6,
        "opponent_games_in_set": 3,
        "current_game_score": "0-0",
    })

    result = engine(client).execute_trade(payload)

    assert result.status == "REJECTED"
    assert result.failure_stage == "set_state_safety"
    assert "impossible closing-set state" in result.reason
    assert client.orders.create_calls == []


def test_execution_safety_gate_blocks_current_set_number_mismatch() -> None:
    client = FakeClient()
    payload = record()
    payload.update({
        "break_lead": 2,
        "best_of_sets": 3,
        "current_set_number": 2,
        "completed_sets": 0,
        "match_closing_set": False,
        "serving_for_match": False,
    })

    result = engine(client).execute_trade(payload)

    assert result.status == "REJECTED"
    assert result.failure_stage == "set_state_safety"
    assert "inconsistent set state" in result.reason
    assert client.orders.create_calls == []
