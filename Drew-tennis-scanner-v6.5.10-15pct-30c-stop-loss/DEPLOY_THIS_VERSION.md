# Deploy Version 6.5.10

1. Replace the repository contents with this ZIP while preserving the existing `.git` folder if using a local clone.
2. Commit every replacement file.
3. Push to GitHub.
4. Redeploy the existing Railway service.
5. Confirm startup reports Version `6.5.10` and `Polymarket execution: LIVE`.

## Entry behavior

Version 6.5.10 submits a cash-sized market order equal to exactly **15%** of authenticated balance, limited by buying power. The submitted market-order field remains `cashOrderQty`.

SHORT/NO keeps `ORDER_INTENT_BUY_SHORT`, `OUTCOME_SIDE_NO`, and `ORDER_ACTION_BUY`. LONG/YES keeps the matching LONG and YES fields.

## Stop-loss behavior

The automatic emergency exit is active at a fixed **30¢ backed-outcome price**. The Railway worker checks open ATP positions each scanner cycle and uses Polymarket's dedicated whole-position `close_position` endpoint when the executable backed price is 30¢ or lower.

Keep the worker continuously deployed. This is a client-side monitor, not an exchange-held stop order.
