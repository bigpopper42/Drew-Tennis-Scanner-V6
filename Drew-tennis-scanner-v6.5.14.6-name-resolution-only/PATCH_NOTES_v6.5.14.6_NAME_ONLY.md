# v6.5.14.6 — Name resolution / discovery only

Baseline: user-provided `Drew-tennis-scanner-v6.5.14.5-name-mapping-fix(2).zip`.

## Why

ATP source identifies `J. C. Prado Angelo` but the authenticated Polymarket match-winner market identifies `Juan Carlos Prado`. Previous code treated `Angelo` as the required entire surname and failed to map `Prado`.

## Edits (strictly limited to name resolution / event discovery)

- Added bounded alias matching for an omitted second family-name token: requires **two aligned given-name tokens** and **one exact full surname token**; never performs fuzzy spelling edits.
- Prevents a multi-token family name from being confused with an optional extra given name.
- Allows explicit `X vs Y` event-title resolution using the same constrained alias matching.
- Adds a first-family-name search term to event-discovery queries when a feed provides a second family name.
- Preserves uniqueness checks, LONG/SHORT side validation, and market-type restrictions; ambiguous identities still reject.
- Adds `tests/test_name_alias_regressions.py` for matching, reversed sides, wrong surnames, ambiguity, and futures rejection.

**No trading decision rules, scoring, sizing, bankroll, stop-loss, order-placement, or monitoring logic have been modified.** This fix addresses a known failure pattern; it does not guarantee live execution if Polymarket API metadata or availability differs.
