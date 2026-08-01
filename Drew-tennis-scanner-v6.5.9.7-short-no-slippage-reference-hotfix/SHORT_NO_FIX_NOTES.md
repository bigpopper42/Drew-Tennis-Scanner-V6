# SHORT/NO Fix Notes — Version 6.5.9.7

## What each live result established

### Version 6.5.9.2

- Explicit SHORT/NO mapping reached the exchange.
- A real order ID was returned.
- The order expired without a fill.

### Versions 6.5.9.3 and 6.5.9.4

- The preview envelope was corrected to `{ "request": order }`.
- The IOC limit approach reached exchange processing but did not fill.

### Version 6.5.9.5

- Switched to a market order but incorrectly replaced `cashOrderQty` with `quantity`.
- Live preview rejected that request before order creation.

### Version 6.5.9.6

- Restored the required `cashOrderQty` market-order field.
- A 97¢ SHORT/NO order passed preview, received an order ID, and reached `order_status`.
- Telemetry revealed that `slippageTolerance.currentPrice` was sent as 3¢, the inverted YES reference, instead of 97¢, the backed NO outcome price.

## Version 6.5.9.7 change

The submitted SHORT/NO market order now uses:

1. `ORDER_TYPE_MARKET`
2. `cashOrderQty` equal to the exact 20% USD stake
3. `ORDER_INTENT_BUY_SHORT`
4. `OUTCOME_SIDE_NO`
5. `ORDER_ACTION_BUY`
6. `TIME_IN_FORCE_IMMEDIATE_OR_CANCEL`
7. `slippageTolerance.currentPrice` equal to the backed NO price
8. Effective tick slippage clamped so the backed price cannot exceed 99¢

The YES reference remains recorded because Polymarket represents limit-order pricing and the underlying binary instrument through the long/YES side. It is no longer incorrectly reused as the market-order slippage reference.

## Exact live example

For the J.J. Wolf SHORT/NO attempt:

- Backed NO price: 97¢
- YES reference: 3¢
- Cash stake: $17.00
- Configured slippage: 3 ticks
- Effective slippage: 2 ticks
- Maximum backed price: 99¢
- New slippage currentPrice: 97¢

## Diagnostic stages

- `preview`: request validation failed before order creation.
- `order_submission`: preview passed, but create failed before an order ID.
- `order_status` with an order ID: the order reached the exchange.
- `EXECUTED`: at least one fill was confirmed.
- `UNFILLED`: no quantity filled within the permitted execution range.

## Stop loss

The planned 40¢ backed-outcome emergency stop remains documented but is not active in Version 6.5.9.7.
