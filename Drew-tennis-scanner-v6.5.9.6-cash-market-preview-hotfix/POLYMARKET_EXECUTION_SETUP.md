# Polymarket US Live Execution Setup — Version 6.5.9.6

The scanner determines whether a tennis setup qualifies. The executor independently resolves and validates the authenticated Polymarket US moneyline before placing an order.

## Locked behavior

- Stake: exactly 20% of authenticated `currentBalance`, rounded down to cents and limited by buying power.
- Submitted market amount: `cashOrderQty` in USD.
- Estimated contracts: calculated at the worst allowed backed-outcome price for minimum-quantity validation and diagnostics only.
- Fixed dollar cap: none in scanner code.
- Distinct markets: may be open simultaneously.
- Same-market exposure: an existing open order, position, or prior trade execution blocks another full order.
- Market type: ordinary match-winner moneyline only.
- Order type: market, immediate-or-cancel, with a three-tick slippage cap.
- Regulatory indicator: `MANUAL_ORDER_INDICATOR_AUTOMATIC`.
- Preview envelope: `{ "request": order }`.
- Confirmation: `EXECUTED` requires exchange fill evidence; a bare order ID remains pending.

## Side mapping

LONG/YES sends:

- `ORDER_INTENT_BUY_LONG`
- `OUTCOME_SIDE_YES`
- `ORDER_ACTION_BUY`

SHORT/NO sends:

- `ORDER_INTENT_BUY_SHORT`
- `OUTCOME_SIDE_NO`
- `ORDER_ACTION_BUY`

For SHORT/NO, the slippage reference remains expressed as the complementary YES price, while `outcomeSide` and `intent` identify the backed NO outcome.

## Railway variables

```text
POLYMARKET_KEY_ID=YOUR_KEY_ID
POLYMARKET_SECRET_KEY=YOUR_SECRET_KEY
POLYMARKET_EXECUTION_ENABLED=true

EXECUTION_MIN_ORDER_USD=0.50
EXECUTION_MIN_PRICE_CENTS=50
EXECUTION_MAX_PRICE_CENTS=99
EXECUTION_SLIPPAGE_TICKS=3
```

`EXECUTION_MIN_MARKET_CONFIDENCE` may remain for compatibility but is not used as a live execution gate.

## Discord meanings

- `EXECUTED`: a full or partial fill was confirmed.
- `PENDING`: the order may exist, but final fill status is unresolved.
- `REJECTED`: permanent validation or exchange rejection.
- `UNFILLED`: IOC canceled or expired with zero fill.
- `FAILED`: temporary discovery, API, transport, order-book, balance, or price failure.

The Discord `Estimated contracts` value is informational. The submitted market amount is the exact cash stake shown on the preceding `Stake` line.

## Planned 40¢ emergency exit

The future protective-exit rule is a fixed 40¢ trigger on the backed outcome. It is not active in Version 6.5.9.6.

## Disable live execution

Set and redeploy:

```text
POLYMARKET_EXECUTION_ENABLED=false
```

Scanning and Discord alerts continue without live order attempts.
