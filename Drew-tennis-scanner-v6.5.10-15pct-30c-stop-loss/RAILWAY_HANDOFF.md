# Railway Handoff — Version 6.5.10

- Cash-sized market entries use `cashOrderQty`.
- Explicit LONG/YES and SHORT/NO direction fields are preserved.
- Live entry sizing is locked at **15%** of authenticated balance, limited by buying power.
- Same-market duplicate protection remains active.
- SHORT/NO backed-price slippage-reference correction remains active.
- Automatic **30¢ stop-loss is active** for authenticated ATP positions.
- Stop monitoring runs once per worker cycle before new entries.
- Stop exits use the dedicated `close_position` endpoint and never submit a guessed quantity.
- Stop status is reported to Discord and Railway logs.
- No database migration is required.

Deploy the flat-root repository to the existing Railway service and preserve the previous deployment commit as the rollback point. Keep Railway continuously running because the 30¢ stop is a client-side monitor.
