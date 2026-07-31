# Deploy Version 6.5.9.5

1. Delete the old local repository contents except `.git` if working from an existing clone.
2. Extract this ZIP into the repository root.
3. Commit every replacement file.
4. Push to GitHub and redeploy Railway.
5. Confirm the startup message reports Version `6.5.9.5` and `Polymarket execution: LIVE`.

## SHORT/NO entry behavior

Version 6.5.9.5 submits a quantity-based market order using explicit `BUY_SHORT`, `OUTCOME_SIDE_NO`, and `ORDER_ACTION_BUY`. It uses the live YES reference price for Polymarket's slippage field and permits at most three adverse ticks. Quantity is sized at that worst allowed price, so maximum spend remains within the locked 20% bankroll stake.

The next Discord execution message will include the order type, quantity, YES bid/ask, backed-outcome price, YES reference price, maximum permitted backed price, slippage ticks, and failure stage.

The proposed emergency exit trigger remains **40¢ on the backed outcome**, but the automatic stop is not active in Version 6.5.9.5.
