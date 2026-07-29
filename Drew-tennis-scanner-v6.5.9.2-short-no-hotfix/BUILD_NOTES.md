# Version 6.5.9.2 Build Notes

## Rebuilt execution module

The old execution path was removed from `scanner/execution.py`. That file is now only a compatibility import for the new implementation in `scanner/polymarket_executor.py`.

The new path is deliberately ordered:

1. Validate the scanner signal.
2. Retrieve the scanner slug if one exists.
3. If that slug is wrong or missing, resolve one exact event from structured hints or player/date identity.
4. List only markets belonging to that event.
5. Authenticate and validate the moneyline and player side.
6. Check exact-market open orders, decimal positions, and prior trade executions.
7. Read the order book, market minimum quantity, tick size, balance, and buying power.
8. Preview the exact request.
9. Submit one IOC market order.
10. Confirm and classify the exchange state without guessing.


## SHORT/NO explicit contract hotfix

- Every live order now sends both supported direction representations: the legacy `intent` and the explicit `outcomeSide` + `action` pair.
- SHORT/NO orders send `ORDER_INTENT_BUY_SHORT`, `OUTCOME_SIDE_NO`, and `ORDER_ACTION_BUY`.
- LONG/YES orders send `ORDER_INTENT_BUY_LONG`, `OUTCOME_SIDE_YES`, and `ORDER_ACTION_BUY`.
- The preview, create response, and final order-status response are checked against the exact authenticated YES/NO outcome selected for the backed player.
- A wrong outcome, non-buy action, unknown side, or conflict between `intent` and `outcomeSide` blocks the order from being reported as successful.
- The LONG-side order-book reference remains authoritative for slippage. For a NO contract priced at 78¢, the request correctly uses the corresponding YES reference price of 22¢.
- The scanner rules, 20% sizing, event resolution, moneyline filtering, duplicate protection, and Cloudflare retry behavior are unchanged.

## Cloudflare/rate-limit hotfix

- Fixed the Brooksby–Moutet failure where a Cloudflare 403 page containing error 1015 was misclassified as a permanent authentication rejection.
- Added one shared 0.20-second minimum interval between Polymarket SDK calls made by this worker.
- Added exponential backoff for definite Cloudflare 1015 and HTTP 429 responses.
- Definite edge throttles are retried; ambiguous order-submission failures are still never blindly replayed.
- Exhausted edge throttles remain retryable from the next fresh qualifying scanner snapshot.
- Raw Cloudflare HTML is replaced with a short safe error message in Railway and Discord.
- The V6.5.9 event-first market resolution and moneyline validation logic was not replaced.

## Regression cases covered

- `J. Mensik vs T. Svajda`, with spread and total markets beside the real moneyline.
- `A. Mannarino vs L. Tien`.
- `M. H. Rehberg vs S. Travaglia`.
- `T. Skatov vs T. Faurel`.
- Exact-score slug first, moneyline on the same event second.
- Generic moneyline title with structured sides and no market-type field.
- Full names, initials, middle initials, surname-first names, boolean strings, and YES/NO outcome flags.
- Network interruption after order submission, with exact-market order, decimal-position, and trade-activity reconciliation.
- Railway worker retries temporary pre-submission failures but suppresses terminal or submitted signals.

## Verification

- `python -m pytest -q`: 158 tests passed in the source tree and from a fresh extraction of the replacement ZIP.
- `python -m compileall -q .`: passed.
- Order direction fields are checked against the current official REST contract. SDK request wrapping and transport are checked against the official Python SDK source, which forwards the supplied request dictionary unchanged.
- No live-money order was submitted during development because production credentials were not used. The first Railway order remains the final integration test.
