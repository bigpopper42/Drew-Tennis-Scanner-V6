# Drew Tennis Scanner Version 6.5.9.7

Version 6.5.9.7 keeps Drew's tennis scanner rules, 20% sizing, and cash-sized market orders unchanged. It corrects the SHORT/NO market-order slippage reference exposed by the live 97¢ NO / 3¢ YES order that reached the exchange but expired without a fill.

## Live execution behavior

- Resolves and validates the exact authenticated two-player moneyline.
- Maps the backed player from authenticated structured market sides.
- Sends the selected outcome explicitly:
  - LONG/YES: `ORDER_INTENT_BUY_LONG`, `OUTCOME_SIDE_YES`, `ORDER_ACTION_BUY`
  - SHORT/NO: `ORDER_INTENT_BUY_SHORT`, `OUTCOME_SIDE_NO`, `ORDER_ACTION_BUY`
- Uses `ORDER_TYPE_MARKET` with `cashOrderQty` equal to exactly 20% of authenticated account balance, limited by buying power.
- Uses immediate-or-cancel execution with bounded tick slippage.
- Uses the **backed outcome's current price** for `slippageTolerance.currentPrice` on both YES and NO orders.
- Retains the inverted YES reference separately for SHORT/NO diagnostics and contract interpretation.
- Clamps effective slippage so the maximum backed price never exceeds the exchange's 99¢ ceiling.
- Uses the production-required preview envelope: `{ "request": order }`.
- Keeps estimated contracts for validation and telemetry only; it does not submit `quantity` on a cash market order.
- Blocks duplicate exposure on the same market through open orders, positions, and trade activity.
- Reports preview, submission, status, fill, partial fill, rejection, pending, and unfilled stages separately.

## Version 6.5.9.7 hotfix

The live V6.5.9.6 order proved that preview, order creation, side mapping, and exchange routing all worked. However, a 97¢ SHORT/NO order sent `slippageTolerance.currentPrice` as the inverted 3¢ YES reference. That field is a slippage reference for the outcome being purchased, not the limit-order `price.value` field. The exchange therefore protected the wrong side of the price scale and the IOC order expired.

This release sends 97¢ as the slippage reference for a 97¢ NO purchase while preserving 3¢ as the YES reference used for side diagnostics. With a configured three-tick cap, the effective allowance is clamped to two ticks so the maximum backed price remains 99¢.

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
4. Confirm startup reports Version `6.5.9.7` and `Polymarket execution: LIVE`.
5. No Supabase migration is required.

See `BUILD_NOTES.md`, `SHORT_NO_FIX_NOTES.md`, and `POLYMARKET_EXECUTION_SETUP.md`.
