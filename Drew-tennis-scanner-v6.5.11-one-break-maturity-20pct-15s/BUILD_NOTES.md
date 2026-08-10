# Version 6.5.11 Build Notes

## Requested changes

1. Added a hard one-break maturity gate:
   - 0 breaks suffered in current set -> at least 4 games won in current set.
   - 1+ breaks suffered in current set -> at least 5 games won in current set.
   - Existing rule rejecting 2+ current-set breaks remains unchanged.
   - Existing one-break consolidation/service confirmation still applies after the new gate.
   - Two-break leads remain exempt from the new minimum-games gate.
2. Restored production entry sizing from 15% to **20%** of authenticated balance.
3. Locked production scanner/stop-monitor cycle from 30 seconds to **15 seconds**. Legacy Railway `EXECUTION_BANKROLL_PCT` and `SCAN_INTERVAL_SECONDS` values are ignored for these locked settings.
4. Preserved the active **30¢ stop-loss**, current LONG/YES execution, and V6.5.9.7 SHORT/NO execution logic.

## Why the new hard rule exists

The observed misses shared a pattern: a one-break lead created in the first one or two games could satisfy the older confirmation logic too early. V6.5.11 requires the set to mature before a one-break lead can qualify. This is an added gate, not a replacement for the other scanner requirements.

## Verification

- One-break player at 3 games won and 0 breaks suffered: blocked.
- One-break player at 4 games won and 0 breaks suffered: maturity gate can pass.
- One-break player at 4 games won after being broken: blocked.
- One-break player at 5 games won after being broken once: maturity gate can pass.
- Two-break lead remains unaffected by the new minimum-games gate.
- Production sizing locked at 20%.
- Production cycle locked at 15 seconds.
- Existing 30¢ LONG and SHORT stop-loss tests retained.
