# Version 6.5.9.1 Build Notes

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

- `python -m pytest -q`: 154 tests passed in the source tree and from a fresh extraction of the replacement ZIP.
- `python -m compileall -q .`: passed.
- Order, search, event, market, position, activity, and preview request keys are checked against the official Python SDK 0.1.2 source contracts.
- No live-money order was submitted during development because production credentials were not used. The first Railway order remains the final integration test.
