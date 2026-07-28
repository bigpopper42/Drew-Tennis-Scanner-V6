# Version 6.5.6 Build Notes

## Fixed: truthful order confirmation

- A returned HTTP success or order ID is no longer counted as a filled order.
- The engine queries `orders.retrieve(order_id)` after submission.
- Top-level and nested SDK response shapes are supported.
- Filled, partially filled, rejected, canceled/unfilled, pending, and failed states are interpreted separately.
- Discord says `ORDER FILL CONFIRMED` only for a verified fill or partial fill.
- Pending orders are reported as unconfirmed instead of falsely reported as placed.
- Railway cycle metrics now include `execution_pending`.

## Fixed: exact-score market selection

- Shared match-winner validation remains active in both discovery and authenticated execution.
- PROP, SPREAD, and TOTAL sports types are rejected.
- Exact-score text including `wins 2-0`, bare `2-0`, `wins 2 sets to 0`, straight-sets wording, and `-es-0-2` slugs is rejected.
- Exact-score text is rejected even when upstream metadata incorrectly labels it as moneyline.
- Exact-score-only events remain unmatched instead of falling back to an unsafe event slug.

## Fixed: authenticated YES/NO mapping

- Live execution no longer falls back to a stale scanner-side value.
- Both competitors must map uniquely to opposite authenticated LONG/SHORT contracts.
- Full names, initials, multi-part surnames, surname-first names, aliases, abbreviations, and boolean-string side flags are supported.
- Ambiguous or malformed side metadata is rejected before preview.

## Changed: live sizing

- Live stake remains locked to 20% of authenticated `currentBalance`.
- The amount is rounded down to cents and cannot exceed buying power.
- The old fixed-dollar maximum cap was removed.
- Legacy `EXECUTION_BANKROLL_PCT` and `EXECUTION_MAX_ORDER_USD` Railway values are ignored.

## Changed: concurrent positions and upgrades

- Multiple different matches may be open simultaneously.
- A same-market position blocks an ordinary duplicate initial signal.
- A scanner-approved `UPGRADE` may add to the existing same-market position.
- Initial and upgrade tiers use distinct execution signal keys.
- An unfinished same-market order still blocks another submission.

## Final verification

- `python -m pytest -q`: 84 tests passed.
- `python -m compileall -q .`: passed.
- Flat-root replacement ZIP verified.
