# Railway Handoff — Version 6.5.9.2

Version 6.5.9.2 replaces the V6.5.8 execution matcher rather than layering another fallback onto it.

- Exact event first; no 520-market fuzzy execution scan.
- `gameId` or `eventSlug` restricts selection to one sporting event.
- Authenticated moneyline and player-side validation remains mandatory.
- Original supported `cashOrderQty` market-order shape restored for exact 20% USD sizing.
- Market-specific quantity and tick metadata checked.
- Distinct markets allowed; duplicate same-market exposure blocked.
- Temporary pre-submission failures retry on a later cycle.
- Submitted orders and exact-market exchange exposure are checked after uncertain responses; unresolved outcomes remain `PENDING` and are not automatically resubmitted.
- Fill confirmation is separate from pending, rejected, and unfilled states.

Deploy the flat-root repository to the existing Railway service. No database migration is required. Preserve the rollback commit before deployment.
