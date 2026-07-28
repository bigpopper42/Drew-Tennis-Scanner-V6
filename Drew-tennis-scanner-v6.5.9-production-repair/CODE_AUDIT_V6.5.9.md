# V6.5.9 Production Repair Audit

## Scope

This build was rebuilt from V6.5.8 after live market-discovery failures for:

- A. Mannarino vs L. Tien
- M. H. Rehberg vs S. Travaglia
- T. Skatov vs T. Faurel

The review covered every Python source file, the Railway worker lifecycle, market discovery, authenticated market validation, order sizing, preview/submission, response interpretation, duplicate handling, retry behavior, and the automated tests.

## Critical defects corrected

1. **Public confidence was incorrectly used as an execution safety gate.**
   A valid candidate slug could be discarded before the authenticated API inspected it. V6.5.9 treats public confidence only as ranking information. Every collected slug must pass authenticated active/open, moneyline, two-player, and side-assignment validation.

2. **The claimed authenticated recovery path was not actually using the official SDK search endpoint.**
   V6.5.9 queries `client.search.query()` using the exact pair, reversed pair, and surnames, recursively extracts nested market slugs, and then validates each through `markets.retrieve_by_slug()`.

3. **Discovery exceptions were collapsed into one generic rejection.**
   Execution results now include a diagnostic stage and detailed discovery/authentication failure reason.

4. **Safe temporary failures were permanently suppressed.**
   Pre-submission discovery and retrieval failures are retryable with bounded exponential backoff. Ambiguous failures during order submission are never automatically retried because a duplicate order may have reached the exchange.

5. **Point-by-point duplicates could fabricate impossible break leads.**
   Point-derived break counts are reconciled against the actual current-set score. For example, a 1-0 score can never be reported as a two-break lead.

6. **Market-specific minimum quantity was ignored.**
   The engine now reads `minimumTradeQty` and rejects orders whose estimated contract quantity is below that market's requirement.

7. **Market-specific tick size was ignored.**
   The engine reads `orderPriceMinTickSize` or `tickSize` and rounds the slippage reference to the market tick.

8. **BUY_SHORT slippage used the LONG/YES reference price.**
   The reference now uses the actual backed contract price for both LONG and SHORT orders.

9. **Preview responses were accepted without checking explicit rejection/error fields.**
   Empty previews and explicit invalid/rejected/failed preview responses now stop submission.

## Safety behavior

- Authenticated market validation is the final market-selection gate.
- Exact-score, set, spread, total, and prop markets remain blocked by `is_match_winner_moneyline()`.
- Both competitors must map uniquely to opposite LONG/SHORT market sides.
- Open orders on the same market block another submission.
- Existing same-market positions block unchanged signals; scanner-approved upgrades remain allowed.
- Non-idempotent order placement is not retried automatically after an ambiguous submission error.
- An order ID alone is not treated as a fill.

## Verification performed

- 104 automated tests passed.
- Full Python bytecode compilation passed.
- Added regression tests for official-SDK market recovery, zero-confidence authenticated candidates, minimum quantity, tick-size rounding, safe retry behavior, impossible break-lead clamping, and SHORT-side price references.

## Remaining limitation

No live-money order was submitted in this build environment because the user's private Polymarket credentials were not available. The code is tested against repository fakes and the current documented official SDK interface, but the first deployment should be watched closely in Railway logs with a small funded account.
