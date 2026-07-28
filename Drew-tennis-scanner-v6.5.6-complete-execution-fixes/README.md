# Drew Tennis Scanner Version 6.5.6

Version 6.5.6 keeps Drew's locked late-match tennis decision tree unchanged and completes the live Polymarket US execution fixes.

## Version 6.5.6 changes

- Trades only the ordinary tennis match-winner moneyline.
- Rejects PROP, SPREAD, TOTAL, exact-score, set-score, set-winner, game-winner, tiebreak, handicap, and total markets.
- Rejects exact-score labels such as `Musetti wins 2-0`, `Musetti 2-0`, `wins 2 sets to 0`, and exact-score slug patterns such as `-es-0-2`.
- Revalidates the authenticated market and both player sides immediately before preview and submission.
- Maps the backed player only from authenticated live market-side metadata. A stale discovery-side value can no longer decide a live order.
- Locks every live entry to 20% of authenticated account balance, rounded down to cents and limited only by available buying power and the exchange's own rules.
- Removes the old fixed-dollar maximum order cap. A legacy `EXECUTION_MAX_ORDER_USD` Railway variable is ignored.
- Allows multiple distinct Polymarket positions at the same time.
- Allows a scanner-approved `UPGRADE` signal to add to an existing same-market position.
- Continues to block unchanged duplicate signals and unfinished same-market orders.
- Verifies the order through `orders.retrieve(order_id)` instead of treating a returned ID as success.
- Discord reports `ORDER FILL CONFIRMED` only after a fill or partial fill is verified. Pending, rejected, canceled, and failed orders use separate truthful statuses.

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

Version 6.5.6 is locked to 20% in code. Legacy Railway variables named `EXECUTION_BANKROLL_PCT` and `EXECUTION_MAX_ORDER_USD` may remain, but this version does not read either one.

## Deployment

1. Replace the GitHub repository contents with this archive.
2. Commit and push.
3. Redeploy the existing Railway service.
4. Confirm Discord reports Version `6.5.6` and `Polymarket execution: LIVE`.
5. No Supabase migration is required.

See `POLYMARKET_EXECUTION_SETUP.md` for live execution details and the emergency stop.
