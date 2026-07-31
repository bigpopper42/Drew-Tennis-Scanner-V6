# Version 6.5.9.6 Build Notes

Version 6.5.9.6 fixes the live preview regression introduced in Version 6.5.9.5 without changing Drew's tennis rules, 20% bankroll sizing, or explicit YES/NO side mapping.

## Live evidence that triggered this release

Railway returned:

`cash_order_qty is required for market order`

The failure occurred during `preview`, before an order was created. Version 6.5.9.5 had replaced `cashOrderQty` with `quantity` for all market orders, which also broke the previously working LONG/YES path.

## Exact changes

1. Restored the live-supported market-order field:
   - `cashOrderQty: {"value": "<20% stake>", "currency": "USD"}`
2. Removed `quantity` from the submitted market-order request.
3. Kept an estimated contract quantity internally for minimum-quantity validation and Discord diagnostics only.
4. Preserved explicit direction fields on every order:
   - LONG/YES: `ORDER_INTENT_BUY_LONG`, `OUTCOME_SIDE_YES`, `ORDER_ACTION_BUY`
   - SHORT/NO: `ORDER_INTENT_BUY_SHORT`, `OUTCOME_SIDE_NO`, `ORDER_ACTION_BUY`
5. Preserved the required preview envelope: `{ "request": order }`.
6. Preserved the three-tick slippage cap and YES-reference conversion for SHORT/NO.
7. Fixed preview-failure telemetry so the backed price, balance, stake, and order book remain visible instead of reverting to zero.
8. Changed the Discord label from `Quantity` to `Estimated contracts` for market orders, because the exchange determines the final contract quantity from the cash amount and fill price.
9. Kept the planned 40¢ emergency stop documented but inactive.

## What the next result means

- `preview` with a different validation message: the cash field is accepted and validation moved to the next request requirement.
- `order_submission`: preview passed; creation was rejected before exchange acceptance.
- An order ID plus `order_status`: the request reached the exchange.
- `EXECUTED`: fill confirmed.
- `UNFILLED`: the order reached the exchange but no quantity filled within the slippage cap.

## Verification

- Full test suite: **162 passing tests**.
- Exact `cash_order_qty is required for market order` regression covered.
- LONG/YES 97¢ telemetry regression covered.
- Exact 76¢ SHORT/NO sizing and conversion scenario covered.
- Preview envelope, side-conflict, duplicate exposure, and uncertain-POST protections covered.
- Python compilation passed.
