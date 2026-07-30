# Drew Tennis Scanner Version 6.5.9.4

Version 6.5.9.4 leaves Drew's tennis decision rules unchanged and replaces the live Polymarket execution path with a separate event-first executor.

## What changed

- Removed the old fuzzy, market-wide execution search that could inspect hundreds of unrelated contracts.
- Uses a supplied market slug first only as a hint; authenticated market data must still prove the contract is the two-player moneyline.
- When the slug is missing or points to a prop, resolves the exact event using `eventSlug`, event ID, `gameId`, or the two players plus event date.
- Lists only markets attached to that event, then rejects spreads, totals, exact-score, set, game, handicap, and other props.
- Maps the backed player from authenticated structured market sides, including initials, middle initials, full names, and surname-first names.
- Sends the backed outcome explicitly on every order: `OUTCOME_SIDE_YES` for LONG/YES or `OUTCOME_SIDE_NO` for SHORT/NO, paired with `ORDER_ACTION_BUY` and the matching legacy intent.
- Verifies the preview and returned order cannot silently change the selected YES/NO outcome.
- Uses a price-capped IOC limit order sized so its maximum cost stays at or below exactly 20% of authenticated account balance, limited by buying power.
- Reads `minimumTradeQty` and `orderPriceMinTickSize` from the selected market before previewing the order.
- Blocks a second order on the same market when an open order, decimal position, or prior trade execution already exists. Different markets may be held simultaneously.
- Preserves an exchange order ID as an idempotency boundary. A pending order is never called filled, and the scanner signal is not resubmitted merely because status polling was interrupted.
- Temporary discovery, price, and connection failures can be tried again on a later scanner cycle instead of being permanently discarded.

## Live safeguards

- Approved and alert-eligible scanner `TRADE` only.
- Exact event and ordinary match-winner moneyline only.
- Both players must map uniquely to opposite LONG/SHORT contracts.
- Active market and open order book required.
- Configured live price range required.
- Market-specific minimum quantity and tick size required.
- Preview request uses the production-required top-level `request` envelope before submission.
- Price-capped IOC limit order with automatic-order regulatory indicator.
- Fill, partial fill, pending, rejected, and unfilled states reported separately.
- The future 40¢ backed-outcome emergency exit is documented but not active in this version.

## Sizing and duplicate policy

- Live order size is locked to 20% of authenticated `currentBalance`, rounded down to cents and capped by buying power.
- There is no fixed dollar maximum in scanner code.
- Distinct markets may be open simultaneously.
- Same-market upgrades do not add another full 20% order. Existing exact-market orders, decimal positions, or prior trade executions block duplicate exposure.

## Deployment

1. Replace the GitHub repository contents with this archive.
2. Commit and push.
3. Redeploy the existing Railway service.
4. Confirm startup reports Version `6.5.9.4` and `Polymarket execution: LIVE`.
5. No Supabase migration is required.

See `POLYMARKET_EXECUTION_SETUP.md` and `EXECUTION_REBUILD_AUDIT.md`.
