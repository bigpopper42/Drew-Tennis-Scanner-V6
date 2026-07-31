# Railway Handoff — Version 6.5.9.5

Version 6.5.9.5 replaces the V6.5.8 execution matcher rather than layering another fallback onto it.

- Exact event first; no 520-market fuzzy execution scan.
- `gameId` or `eventSlug` restricts selection to one sporting event.
- Authenticated moneyline and player-side validation remains mandatory.
- Quantity-based market entries use explicit contract quantity and a three-tick slippage cap while keeping maximum cost at or below exact 20% USD sizing.
- Market-specific quantity and tick metadata checked.
- Distinct markets allowed; duplicate same-market exposure blocked.
- Temporary pre-submission failures retry on a later cycle.
- Submitted orders and exact-market exchange exposure are checked after uncertain responses; unresolved outcomes remain `PENDING` and are not automatically resubmitted.
- Fill confirmation is separate from pending, rejected, and unfilled states.
- Default `ORD_REJECT_REASON_EXCHANGE_OPTION` is ignored unless the exchange actually reports a rejected state.
- The future 40¢ backed-outcome emergency exit is documented but not active.

Deploy the flat-root repository to the existing Railway service. No database migration is required. Preserve the rollback commit before deployment.
