# Version 6.5.4 Build Notes

## Execution fixes

- Keeps Drew's locked tennis scanner strategy unchanged.
- Preserves the explicit backed-player handoff shown as `Trade: <player>` in Discord.
- Removes the premature rejection that required the public-discovery side before the authenticated market was retrieved.
- Uses authenticated `marketSides[].team` names and `marketSides[].long` as the authoritative player-to-YES/NO mapping.
- Supports accents, punctuation differences, capitalization, whitespace, full first names, and first initials while requiring compatible surnames.
- Rejects ambiguous mappings, same-side mappings, duplicate side identities, and genuinely unsafe names.
- Uses title, question, slug, and description only when structured market-side names are unavailable.
- Correctly unwraps the documented order-book response from `marketData` before reading `state`, `bids`, and `offers`.
- No longer reports a missing top-level `state` as a suspended market.
- Reports the actual non-open state returned by Polymarket US and separately reports a missing state.
- Replaces the misleading scanner-tier Discord line with `Live order size: 10% of authenticated balance`.

## Safeguards preserved

- `TRADE` decision and alert eligibility requirements
- safe market discovery and minimum match confidence
- active/open market checks
- live price sanity range
- authenticated balance and buying-power checks
- 10% bankroll sizing with minimum and maximum order limits
- one-open-order and one-open-position limits
- preview before submit
- immediate-or-cancel order behavior
- duplicate-signal protection

## Validation

- Complete test suite: `64 passed, 0 failed`
- Python compilation check passed
- Tests use fake clients and do not place real orders

A live Railway signal is still required to validate the authenticated production API and actual order submission end to end.
