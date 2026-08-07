# Drew Tennis Scanner Version 6.5.10

Version 6.5.10 keeps the current tennis decision tree and SHORT/NO execution work, changes live entry sizing from **20% to 15% of authenticated balance**, and activates a **30¢ automatic stop-loss** for live ATP positions.

## Live entry behavior

- Resolves and validates the exact authenticated two-player moneyline.
- LONG/YES sends `ORDER_INTENT_BUY_LONG`, `OUTCOME_SIDE_YES`, `ORDER_ACTION_BUY`.
- SHORT/NO sends `ORDER_INTENT_BUY_SHORT`, `OUTCOME_SIDE_NO`, `ORDER_ACTION_BUY`.
- Uses `ORDER_TYPE_MARKET` with `cashOrderQty` equal to exactly **15%** of authenticated account balance, limited by buying power.
- Uses immediate-or-cancel execution with bounded tick slippage.
- Uses the backed outcome's current price for `slippageTolerance.currentPrice` on both YES and NO entries.
- Keeps the complementary YES reference separately for SHORT/NO diagnostics.
- Blocks duplicate exposure on the same market through open orders, positions, and trade activity.

## Active 30¢ stop-loss

- The trigger is a fixed **30¢ backed-outcome price**, not a 30% loss calculation.
- The worker checks live ATP positions every scanner cycle.
- LONG/YES is evaluated against the best executable YES bid.
- SHORT/NO is evaluated against the executable NO bid, calculated as `1 - best YES offer`.
- At 30¢ or below, the executor calls Polymarket's dedicated `close_position` endpoint for the existing position.
- No position quantity is submitted to the close endpoint, preventing a stale quantity from accidentally creating an opposite position.
- Stop exits use three ticks of slippage protection and report status through Discord.
- Because this is a client-side monitor rather than an exchange-held stop order, the worker must be running. With the default configuration it checks once per 30-second scanner cycle, so a fast market can move below 30¢ before the close is submitted.
- The stop monitor reconstructs open ATP positions from the authenticated portfolio after a restart. As a result, any manual ATP position held in the same Polymarket account is also subject to the 30¢ stop.

## Risk controls

- Approved and alert-eligible scanner `TRADE` only.
- Ordinary match-winner moneyline only.
- Active market and usable order book required.
- Fixed live allocation: **15%** of balance, rounded down to cents and capped by buying power.
- Distinct markets may be held simultaneously; duplicate same-market exposure is blocked.
- Automatic 30¢ stop-loss active for open ATP positions.

## Deployment

1. Replace the GitHub repository contents with this archive.
2. Commit and push.
3. Redeploy Railway.
4. Confirm startup reports Version `6.5.10`, `Polymarket execution: LIVE`, 15% sizing, and a 30¢ stop trigger.
5. No Supabase migration is required.

See `BUILD_NOTES.md`, `STOP_LOSS_IMPLEMENTATION.md`, and `POLYMARKET_EXECUTION_SETUP.md`.
