# Deploy Version 6.5.12.2

1. Replace the repository contents with this ZIP while preserving the existing `.git` folder if using a local clone.
2. Commit every replacement file.
3. Push to GitHub.
4. Redeploy the existing Railway service.
5. Confirm startup reports Version `6.5.12.2` and `Polymarket execution: LIVE`.

## Entry behavior

Version 6.5.12.2 submits a cash-sized market order equal to exactly **20%** of authenticated balance, limited by buying power. The submitted market-order field remains `cashOrderQty`.

SHORT/NO keeps `ORDER_INTENT_BUY_SHORT`, `OUTCOME_SIDE_NO`, and `ORDER_ACTION_BUY`. LONG/YES keeps the matching LONG and YES fields.

## Stop-loss behavior

The automatic emergency exit is active at a fixed **30¢ backed-outcome price**. The Railway worker checks open ATP positions each scanner cycle and uses Polymarket's dedicated whole-position `close_position` endpoint when the executable backed price is 30¢ or lower.

Keep the worker continuously deployed. This is a client-side monitor, not an exchange-held stop order.

## Scanner logic changed in 6.5.12.2

1. Qualifying events are detected from `event_qualification` and qualifying/qualification round text.
2. Qualifier ranking gate: backed #1-150 may face any opponent; backed #151-200 require opponent #450 or worse; backed #201-250 require opponent #750 or worse; backed #251+ are blocked. Missing backed rank always blocks, and missing opponent rank blocks the 151-250 tiers.
3. A fresh one-break lead created at four games must reach 40-0 in the following backed-player service game.
4. A fresh one-break lead created at five games must reach 30-0 in the following backed-player service game.
5. Production entry sizing remains locked to 20%, stop trigger remains 30¢, and worker interval remains 15 seconds.
