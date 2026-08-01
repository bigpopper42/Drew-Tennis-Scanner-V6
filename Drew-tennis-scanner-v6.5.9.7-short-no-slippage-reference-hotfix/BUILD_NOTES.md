# Version 6.5.9.7 Build Notes

Version 6.5.9.7 fixes the remaining live SHORT/NO slippage-reference defect without changing Drew's tennis rules, exact 20% bankroll sizing, cash market-order format, or explicit YES/NO mapping.

## Live evidence that triggered this release

The 97¢ SHORT/NO order produced:

- Preview accepted
- Exchange order ID created
- `ORDER_STATE_EXPIRED`
- Visible YES bid: 3¢
- Visible NO price: 97¢
- Submitted slippage reference: 3¢

That established that the request reached the matching engine but the slippage reference was on the wrong price scale.

## Exact changes

1. `slippageTolerance.currentPrice` now uses the backed outcome's executable price:
   - LONG/YES at 97¢ -> currentPrice 0.97
   - SHORT/NO at 97¢ -> currentPrice 0.97
2. The inverted YES reference remains available separately for SHORT/NO diagnostics:
   - SHORT/NO 97¢ -> YES reference 3¢
3. Effective slippage ticks are clamped against the 99¢ exchange ceiling:
   - 97¢ with configured 3 ticks -> effective 2 ticks -> maximum 99¢
   - 76¢ with configured 3 ticks -> effective 3 ticks -> maximum 79¢
4. Preserved `cashOrderQty`, which the live preview endpoint requires for market orders.
5. Preserved `ORDER_INTENT_BUY_SHORT`, `OUTCOME_SIDE_NO`, and `ORDER_ACTION_BUY` together.
6. Preserved the preview request envelope, IOC handling, duplicate protection, and full failure-stage telemetry.
7. Kept the planned 40¢ emergency stop documented but inactive.

## What the next result means

- Discord showing a 97¢ SHORT with `Slippage cap: 2 tick(s)` confirms V6.5.9.7 is deployed.
- `preview`: the request did not reach order creation; the new reason identifies the next validation issue.
- `order_submission`: preview passed, but creation failed before an order ID.
- An order ID plus `order_status`: the request reached the exchange.
- `EXECUTED`: at least one SHORT/NO contract filled, confirming the full path.
- `UNFILLED`: side mapping and request shape still reached the exchange, but the raw live market or cash-order behavior requires the next diagnosis.

## Verification

- Exact 97¢ SHORT/NO, 3¢ YES-bid regression covered.
- Backed-outcome slippage reference covered for LONG and SHORT.
- 99¢ ceiling tick-clamping covered.
- 76¢ SHORT/NO cash sizing and three-tick path covered.
- Preview envelope, cash-order requirement, side conflicts, duplicate exposure, and uncertain-POST protections covered.
- Full Python compilation passed.
