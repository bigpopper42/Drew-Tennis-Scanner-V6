# Drew Tennis Scanner Version 6.5.8

Version 6.5.8 keeps Drew's locked late-match tennis decision tree unchanged and completes the live Polymarket US execution fixes.

## Version 6.5.8 changes

- Stops requiring the incomplete public search response to fully prove a moneyline before the authenticated trading API can inspect it.
- Keeps valid ATP Challenger slugs as provisional candidates when public market-type or named-side fields are omitted.
- Continues to reject obvious exact-score, set, game, spread, total, tiebreak, and proposition markets during discovery.
- Fixes `M. H. Rehberg` matching against `Max Hans Rehberg` in both discovery and authenticated player-side mapping.
- When the worker finds no slug, the execution engine performs a fresh lookup instead of immediately returning `Polymarket US market was not safely matched.`
- Execution validates ranked candidates one by one, so an exact-score or incomplete result appearing first cannot hide the real moneyline later in the search results.
- The execution engine still retrieves the selected market through the authenticated API and independently validates active status, moneyline type, both competitors, opposite LONG/SHORT contracts, order-book state, and live price before preview or submission.
- Preserves the Skatov/Faurel exact-score fallback fix.
- Locks every live entry to 20% of authenticated account balance, rounded down to cents and limited by buying power.
- Allows simultaneous positions on different markets and scanner-approved same-market upgrades.
- Verifies the submitted order state before Discord reports a confirmed fill.

## Safeguards retained

- The scanner record must be an approved, alert-eligible `TRADE`.
- Market-match confidence must meet the configured minimum.
- Both live player names must map uniquely to opposite LONG/SHORT contracts.
- The authenticated market and order book must be active and open.
- The backed-player price must stay inside the configured execution range.
- The calculated 20% order must meet the configured minimum order amount.
- The exact request is previewed before submission.
- Orders use immediate-or-cancel behavior and are marked automatically generated.
- The worker prevents repeated execution of the same initial signal or the same upgrade tier while the process is running.

## Important sizing note

Version 6.5.8 is locked to 20% in code. Legacy Railway variables named `EXECUTION_BANKROLL_PCT` and `EXECUTION_MAX_ORDER_USD` may remain, but this version does not read either one.

## Deployment

1. Replace the GitHub repository contents with this archive.
2. Commit and push.
3. Redeploy the existing Railway service.
4. Confirm Discord reports Version `6.5.8` and `Polymarket execution: LIVE`.
5. No Supabase migration is required.

See `POLYMARKET_EXECUTION_SETUP.md` for live execution details and the emergency stop.
