# Version 6.5.8 Build Notes

## Fixed: valid markets discarded before authenticated validation

V6.5.7 required the incomplete public search payload to prove that a candidate was the match-winner moneyline. Some ATP Challenger markets expose a valid slug publicly while omitting the sports market type or showing only generic YES/NO sides. Those valid candidates were discarded before the authenticated trading API could inspect them.

V6.5.8 separates discovery from execution safety:

- Obvious exact-score, set, game, spread, total, tiebreak, and proposition markets are still rejected during discovery.
- A public candidate with the correct two-player event identity and no non-moneyline signature can be retained provisionally.
- The authenticated execution API remains the decisive gate for active status, match-winner type, player names, LONG/SHORT assignment, order-book state, and price.
- Publicly incomplete candidates are never treated as authorization to trade by themselves.

## Fixed: Rehberg middle-initial mismatch

- `M. H. Rehberg` now maps to `Max Hans Rehberg`, `Max Rehberg`, and surname-first provider formats.
- Middle initials are treated as optional identity evidence instead of surname components.
- The same name-matching behavior is used in public discovery and authenticated player-side mapping.
- Compound surnames such as `Pascual Ferra` remain supported.

## Added: execution-side market recovery

- When the worker record contains no market slug, the execution engine performs one fresh market lookup itself.
- The recovered candidate must meet the market-confidence minimum.
- Every ranked candidate is retrieved through the SDK in order until one passes the existing market-type and player-name safeguards.
- A prop or malformed candidate appearing first no longer prevents a valid moneyline later in the result set from being used.
- A missed public worker lookup can no longer cause an immediate rejection without the execution engine trying to resolve the market.

## Preserved safeguards

- Match-winner moneyline only.
- Authenticated two-player LONG/SHORT mapping only.
- Exact-score and other side markets blocked.
- 20% of authenticated balance, rounded down to cents, with no scanner dollar cap.
- Unlimited distinct open markets and scanner-approved same-market upgrades.
- Duplicate signals and unfinished same-market orders blocked.
- Fill confirmation required before Discord reports success.

## Verification

- `python -m pytest -q`: 98 tests passed.
- `python -m compileall -q .`: passed.
- `API_TENNIS_KEY=test DRY_RUN=true python worker.py --check-config`: passed.
- Direct regressions cover `M. H. Rehberg vs S. Travaglia` and `T. Skatov vs T. Faurel`.
