# Version 6.5.13 Build Notes

## Critical one-break execution hardening

V6.5.13 removes the legacy early-set one-break confirmation path and duplicates the minimum-game/fresh-break consolidation checks at the Polymarket execution boundary. A record cannot execute with a one-break lead before 4 current-set games (or 5 after being broken), even if an upstream component incorrectly labels it TRADE. Fresh breaks at 4 require 40-0 while serving for game five; fresh breaks at 5 require 30-0 while serving for game six.


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

The observed misses shared a pattern: a one-break lead created in the first one or two games could satisfy the older confirmation logic too early. V6.5.13 requires the set to mature before a one-break lead can qualify. This is an added gate, not a replacement for the other scanner requirements.

## Verification

- One-break player at 3 games won and 0 breaks suffered: blocked.
- One-break player at 4 games won and 0 breaks suffered: maturity gate can pass.
- One-break player at 4 games won after being broken: blocked.
- One-break player at 5 games won after being broken once: maturity gate can pass.
- Two-break lead remains unaffected by the new minimum-games gate.
- Production sizing locked at 20%.
- Production cycle locked at 15 seconds.
- Existing 30¢ LONG and SHORT stop-loss tests retained.

## Version 6.5.13 scanner hardening

Live review found that four of five observed misses clustered in volatile qualification matches involving low-ranked players. Version 6.5.13 uses a tiered qualification-specific hard gate: backed ATP ranks 1-150 may face any opponent; backed ranks 151-200 require an opponent ranked 450 or worse; backed ranks 201-250 require an opponent ranked 750 or worse; backed ranks 251+ are blocked. Missing backed-player ranking always blocks, and opponent ranking is required for the 151-250 tiers. Main-draw ATP Tour and Challenger matches keep the existing ranking treatment.

The release also closes a one-break consolidation loophole. When the most recently completed game was a break by the backed player:

- if that break leaves the backed player on four games and they serve for game five, the service game must reach 40-0 before the trade can qualify;
- if that break leaves the backed player on five games and they serve for game six, the service game must reach 30-0 before the trade can qualify.

The mapper reads current point-by-point history so reaching the threshold remains recognized even if the next point changes the visible score. Existing 4-game/5-game one-break maturity rules remain in force.
