# Drew Tennis Scanner Version 6.5.9.6

Version 6.5.9.6 keeps Drew's tennis scanner rules unchanged and repairs the Polymarket market-order request after the live endpoint reported `cash_order_qty is required for market order`.

## Live execution behavior

- Resolves and validates the exact authenticated two-player moneyline.
- Maps the backed player from authenticated structured market sides.
- Sends the selected outcome explicitly:
  - LONG/YES: `ORDER_INTENT_BUY_LONG`, `OUTCOME_SIDE_YES`, `ORDER_ACTION_BUY`
  - SHORT/NO: `ORDER_INTENT_BUY_SHORT`, `OUTCOME_SIDE_NO`, `ORDER_ACTION_BUY`
- Uses `ORDER_TYPE_MARKET` with `cashOrderQty` equal to exactly 20% of authenticated account balance, limited by buying power.
- Uses immediate-or-cancel execution with a three-tick slippage cap.
- Uses the live YES reference price for slippage, including the required inversion for SHORT/NO.
- Uses the production-required preview envelope: `{ "request": order }`.
- Keeps estimated contracts for validation and telemetry only; it does not submit `quantity` on a cash market order.
- Blocks duplicate exposure on the same market through open orders, positions, and trade activity.
- Reports preview, submission, status, fill, partial fill, rejection, pending, and unfilled stages separately.

## Version 6.5.9.6 hotfix

Version 6.5.9.5 incorrectly replaced `cashOrderQty` with `quantity`, causing the live preview endpoint to reject even LONG/YES orders. This release restores `cashOrderQty` and preserves all newer SHORT/NO mapping and diagnostics.

Preview failures now retain the actual backed price, balance, stake, YES bid/ask, YES reference, estimated contracts, slippage cap, and failure stage. Market-order Discord messages label contract count as `Estimated contracts` because the exchange determines the final filled quantity.

## Risk controls

- Approved and alert-eligible scanner `TRADE` only.
- Ordinary match-winner moneyline only.
- Active market and open order book required.
- Configured live-price range required.
- Market-specific minimum quantity and tick size required.
- Fixed live allocation: 20% of balance, rounded down to cents and capped by buying power.
- Distinct markets may be held simultaneously; duplicate same-market exposure is blocked.
- The planned 40¢ backed-outcome emergency stop is documented but not active.

## Deployment

1. Replace the GitHub repository contents with this archive.
2. Commit and push.
3. Redeploy Railway.
4. Confirm startup reports Version `6.5.9.6` and `Polymarket execution: LIVE`.
5. No Supabase migration is required.

See `BUILD_NOTES.md`, `SHORT_NO_FIX_NOTES.md`, and `POLYMARKET_EXECUTION_SETUP.md`.
