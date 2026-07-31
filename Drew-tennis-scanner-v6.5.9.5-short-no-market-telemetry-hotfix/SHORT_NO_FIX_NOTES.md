# SHORT/NO Fix Notes — Version 6.5.9.5

## Why the prior versions did not complete a SHORT/NO trade

### Version 6.5.9.2

- Correctly identified `ORDER_INTENT_BUY_SHORT` and `OUTCOME_SIDE_NO`.
- Used a market order with `cashOrderQty`.
- The current Retail Orders contract documents `quantity` as required for market orders; `cashOrderQty` is not the supported quantity path used by this rebuild.
- Result: the exchange could assign an order ID but the order could expire without a fill.

### Version 6.5.9.3 / 6.5.9.4

- Replaced the cash market request with explicit contract `quantity`.
- Used a price-capped IOC limit order.
- Preview routing was fixed in 6.5.9.4, but the synthetic SHORT/NO limit still expired without a fill when no immediately executable quantity remained at the submitted reference price.

## Version 6.5.9.5 change

The entry now combines the parts that match the official order contract:

1. `ORDER_TYPE_MARKET`
2. Explicit decimal contract `quantity`
3. `ORDER_INTENT_BUY_SHORT`
4. `OUTCOME_SIDE_NO`
5. `ORDER_ACTION_BUY`
6. `TIME_IN_FORCE_IMMEDIATE_OR_CANCEL`
7. `slippageTolerance.currentPrice` expressed as the required YES/long reference price
8. Three ticks of adverse slippage protection

The quantity is calculated at the worst allowed backed-outcome price. That means the maximum potential spend remains at or below the locked 20% stake even if the market moves the full three ticks before filling.

## Example from the live 76¢ NO failure

For an $81.95 account:

- Stake: $16.39
- Visible NO price: 76¢
- YES reference: 24¢
- Maximum NO price: 79¢
- Submitted quantity: 20.74 contracts
- Maximum spend: 20.74 × $0.79 = $16.3846

## New Discord diagnostics

Every order attempt after the book lookup now reports:

- order type
- contract quantity
- slippage ticks
- visible YES bid and ask
- backed-outcome price
- YES reference price
- maximum allowed backed-outcome price
- exact failure stage
- exchange order state and order ID

This makes the next result diagnostic:

- `preview` failure means request validation is still blocking the order.
- `order_submission` failure means the create request was rejected before exchange acceptance.
- an order ID plus `order_status` means the order reached the exchange.
- `FILLED` confirms the first completed SHORT/NO execution.
- `NO_LIQUIDITY` or an unfilled market order means the request shape and side mapping worked, but executable depth disappeared beyond the three-tick cap.

## Stop loss

The planned 40¢ backed-outcome emergency stop remains documented but is not active in Version 6.5.9.5.
