# Polymarket US Live Execution Setup — Version 6.5.10

The scanner determines whether a tennis setup qualifies. The executor independently resolves and validates the authenticated Polymarket US moneyline before placing an order.

## Locked entry behavior

- Stake: exactly **15%** of authenticated `currentBalance`, rounded down to cents and limited by buying power.
- Submitted market amount: `cashOrderQty` in USD.
- Fixed dollar cap: none in scanner code.
- Distinct markets: may be open simultaneously.
- Same-market exposure: an existing open order, position, or prior execution blocks another full entry.
- Market type: ordinary match-winner moneyline only.
- Order type: market, immediate-or-cancel, with bounded slippage.
- Regulatory indicator: `MANUAL_ORDER_INDICATOR_AUTOMATIC`.
- Preview envelope: `{ "request": order }`.
- Confirmation: `EXECUTED` requires exchange fill evidence; a bare order ID remains pending.

## Side mapping

LONG/YES sends `ORDER_INTENT_BUY_LONG`, `OUTCOME_SIDE_YES`, and `ORDER_ACTION_BUY`.

SHORT/NO sends `ORDER_INTENT_BUY_SHORT`, `OUTCOME_SIDE_NO`, and `ORDER_ACTION_BUY`.

For SHORT/NO entries, `slippageTolerance.currentPrice` is the backed NO price. The complementary YES price remains separate for diagnostics and market interpretation.

## Active 30¢ stop-loss

- Trigger: executable backed-outcome price <= **30¢**.
- LONG/YES executable price: best YES bid.
- SHORT/NO executable price: `1 - best YES offer`.
- Exit method: Polymarket US `orders.close_position` whole-position endpoint.
- Submitted close request intentionally contains no local position quantity.
- Exit slippage protection: 3 ticks.
- Scope: authenticated open ATP positions.
- Frequency: once per worker/scanner cycle (30 seconds by default).
- Restart behavior: positions are rediscovered from the authenticated portfolio.

Because the SDK does not expose a native STOP order type, Railway must be running for this protection to operate. A rapid move can execute materially below 30¢ before the next cycle/close.

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

The production bankroll percentage and stop trigger are locked in code at 15% and 30¢ in this release.

## Disable live execution

Set and redeploy:

```text
POLYMARKET_EXECUTION_ENABLED=false
```

Scanning and Discord alerts continue without live order attempts or automatic stop closes.
