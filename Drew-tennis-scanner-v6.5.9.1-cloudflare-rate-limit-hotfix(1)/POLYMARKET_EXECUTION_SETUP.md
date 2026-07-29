# Polymarket US Live Execution Setup — Version 6.5.9.1

The scanner decides whether a tennis setup qualifies. The rebuilt executor independently resolves and validates the corresponding Polymarket US moneyline before placing an order.

## Locked behavior

- Stake: exactly 20% of authenticated `currentBalance`, rounded down to cents and limited by buying power.
- Order amount field: `cashOrderQty` in USD.
- Fixed dollar cap: none in scanner code.
- Distinct markets: may be open simultaneously.
- Same-market exposure: an existing open order, decimal position, or prior trade execution blocks another full 20% order, including an upgrade signal.
- Market type: ordinary match-winner moneyline only.
- Order type: IOC market order.
- Regulatory indicator: `MANUAL_ORDER_INDICATOR_AUTOMATIC`.
- Preview: official `{"request": order}` wrapper.
- Confirmation: a fill is reported only from an exchange fill state or execution; a bare order ID is pending, not filled.

## Event-first market resolution

The executor does not perform a market-wide fuzzy candidate hunt.

1. It validates a supplied scanner slug if available.
2. A wrong prop slug can still contribute its `eventSlug` or `gameId` as an event hint.
3. Otherwise it finds the event using event hints or the two player names and event date.
4. It lists only markets attached to that event using `gameId` or `eventSlug`.
5. It selects one authenticated moneyline that maps both players to opposite LONG/SHORT contracts.
6. Ambiguous events or multiple equally valid moneylines are rejected rather than guessed.

## Non-moneyline protection

The executor blocks explicit spread, total, prop, exact-score, handicap, set, game-number, margin, first-to, and race-to markets. A missing market-type field can be accepted only when there are exactly two named player sides, one LONG and one SHORT, no line value, and no prop signature.

## Market and order checks

Before submission, the executor requires:

- an approved, alert-eligible scanner trade;
- two different players;
- an active, non-closed authenticated market;
- unique player mapping to opposite contracts;
- an open order book and executable side liquidity;
- a live price inside the configured range;
- valid `minimumTradeQty` and `orderPriceMinTickSize` from the market;
- enough balance and buying power for the minimum trade;
- no existing exact-market open order, decimal position, or prior trade execution;
- a successful order preview.

## Retry and duplicate behavior

- Event lookup, market retrieval, order-book, balance, price, and network failures before confirmed submission remain eligible for a later scanner cycle.
- Once Polymarket returns an order ID, the signal is terminal for submission purposes even if its final state is pending.
- If submission raises after it may have reached the exchange, the executor checks that exact market for an order, decimal position, or trade execution. If the outcome is still unknown, it returns `PENDING` and suppresses automatic resubmission rather than assuming the order failed.

## Railway variables

```text
POLYMARKET_KEY_ID=YOUR_KEY_ID
POLYMARKET_SECRET_KEY=YOUR_SECRET_KEY
POLYMARKET_EXECUTION_ENABLED=true

EXECUTION_MIN_ORDER_USD=0.50
EXECUTION_MIN_PRICE_CENTS=50
EXECUTION_MAX_PRICE_CENTS=99
EXECUTION_SLIPPAGE_TICKS=1
```

`EXECUTION_MIN_MARKET_CONFIDENCE` may remain in Railway for compatibility, but Version 6.5.9.1 does not use it in live execution.

## Discord meanings

- `EXECUTED`: full or partial fill confirmed.
- `PENDING`: an open/submitted order exists, but a final fill was not confirmed.
- `REJECTED`: a permanent validation failure or exchange rejection.
- `UNFILLED`: IOC canceled or expired without a fill.
- `FAILED`: a temporary pre-submission discovery, API, transport, book, balance, or price failure.

## Emergency stop

Set and redeploy:

```text
POLYMARKET_EXECUTION_ENABLED=false
```

Scanning and Discord alerts continue without live order attempts.
