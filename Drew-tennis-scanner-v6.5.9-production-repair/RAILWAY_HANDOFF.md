# Railway Handoff — Version 6.5.9

V6.5.9 fixes the market-matching regressions without weakening the authenticated execution safeguards:

- public ATP Challenger candidates may proceed provisionally when type or named-side fields are omitted;
- exact-score and other non-moneyline signatures remain blocked;
- `M. H. Rehberg` correctly maps to `Max Hans Rehberg`;
- if the worker has no slug, execution performs a fresh lookup before rejecting;
- execution checks ranked candidates through the SDK until it finds the first authenticated match-winner market matching both players, rather than trusting the first public result;
- the authenticated market must still be active, match-winner moneyline, and map both players uniquely to opposite LONG/SHORT contracts;
- 20% live sizing, unlimited distinct markets, same-market upgrades, duplicate protection, and verified fill reporting remain unchanged.

Deploy the flat-root repository to the existing Railway service. No database migration is required. Keep `POLYMARKET_EXECUTION_ENABLED=true` for live orders or set it to `false` for the emergency stop.
