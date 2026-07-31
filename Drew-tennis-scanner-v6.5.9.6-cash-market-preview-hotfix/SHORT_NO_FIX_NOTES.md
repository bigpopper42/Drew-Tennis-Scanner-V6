# SHORT/NO Fix Notes — Version 6.5.9.6

## What each live result established

### Version 6.5.9.2

- Explicit SHORT/NO mapping reached the exchange.
- A real order ID was returned.
- The order expired without a fill.
- This proved the system had moved beyond the original side-mapping rejection.

### Versions 6.5.9.3 and 6.5.9.4

- The preview envelope was corrected to `{ "request": order }`.
- The SHORT/NO request used a synthetic IOC limit order.
- The order could reach the exchange but expire when no executable quantity remained at the allowed price.

### Version 6.5.9.5

- Switched both sides to a market order with `quantity`.
- Live preview rejected the request with `cash_order_qty is required for market order`.
- Because this field change applied to both directions, it temporarily broke the previously working LONG/YES path too.

## Version 6.5.9.6 change

The submitted order now uses the field confirmed by the live endpoint:

1. `ORDER_TYPE_MARKET`
2. `cashOrderQty` equal to the exact 20% USD stake
3. Matching explicit `intent`
4. Matching explicit `outcomeSide`
5. `ORDER_ACTION_BUY`
6. `TIME_IN_FORCE_IMMEDIATE_OR_CANCEL`
7. `slippageTolerance.currentPrice` expressed as the YES reference price
8. Three adverse slippage ticks

The internally calculated contract count is not sent as `quantity`. It is retained only to confirm the stake can meet `minimumTradeQty` at the worst permitted price and to provide useful diagnostics.

## Example: 76¢ SHORT/NO with an $81.95 account

- Cash order: $16.39
- Visible NO price: 76¢
- YES reference: 24¢
- Maximum permitted NO price: 79¢
- Estimated contracts at the maximum price: 20.74
- Submitted amount: exactly $16.39 through `cashOrderQty`

## Diagnostic stages

- `preview`: the exchange rejected request validation before order creation.
- `order_submission`: preview passed, but create failed before an order ID was accepted.
- `order_status` with an order ID: the order reached the exchange.
- `EXECUTED`: at least one fill was confirmed.
- `UNFILLED`: no quantity filled within the allowed execution range.

## Stop loss

The planned 40¢ backed-outcome emergency stop remains documented but is not active in Version 6.5.9.6.
