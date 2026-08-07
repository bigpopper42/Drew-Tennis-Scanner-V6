# Version 6.5.10 Build Notes

Version 6.5.10 changes two live risk settings requested by Drew while preserving the current scanner rules and SHORT/NO entry logic.

## Changes

1. Live entry allocation changed from **20% to 15%** of authenticated account balance.
2. The production worker locks entry sizing at 15%; legacy `EXECUTION_BANKROLL_PCT` remains ignored.
3. Added an active **30¢ stop-loss** based on the executable price of the outcome actually held.
4. LONG/YES stop check uses best YES bid.
5. SHORT/NO stop check uses `1 - best YES offer`, which is the executable NO bid.
6. When the stop triggers, the executor uses Polymarket's dedicated `close_position` endpoint rather than submitting a guessed quantity.
7. Stop monitoring runs before new entry execution on every scanner cycle.
8. Open ATP positions are rediscovered from the authenticated portfolio after restarts.
9. Added Discord stop-loss messages and cycle counters for triggers, confirmed exits, and errors.
10. Preserved the current cash-sized entry format, explicit YES/NO mapping, preview envelope, IOC behavior, duplicate protection, and SHORT/NO slippage-reference fix.

## Important stop behavior

The 30¢ stop is **client-side**, not an exchange-held stop order. The current Polymarket US SDK exposes LIMIT and MARKET order types, so the Railway worker must be running for the monitor to act. The default worker cycle is 30 seconds; a fast market can gap below the trigger before the close request reaches the exchange.

The monitor intentionally scans authenticated ATP positions so protection survives a Railway restart. If a manual ATP position exists in the same Polymarket account, it will also be managed by this stop rule.

## Verification

- 15% production sizing regression covered.
- LONG stop triggers at exactly 30¢.
- SHORT/NO stop triggers when executable NO bid reaches exactly 30¢.
- 31¢ does not trigger.
- Non-ATP positions are ignored.
- Close request contains no `quantity` or `cashOrderQty`.
- Discord stop-loss reporting covered.
- Existing execution regression suite retained.
