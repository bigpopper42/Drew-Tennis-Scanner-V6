# Polymarket Execution Rebuild Audit — Version 6.5.11

## Bottom line

Version 6.5.11 does **not** reuse the V6.5.6–V6.5.8 execution matcher. The live execution authority is now `scanner/polymarket_executor.py`; `scanner/execution.py` is only a compatibility re-export.

This audit reviewed all 21 production Python files (9,545 lines), all 11 Python test files (3,419 lines), deployment/configuration files, and the SQL schema/migrations. The review included full source reading, execution-path tracing, AST/static scans, comparison with the available V6.5.5 and V6.5.8 repositories, compilation, configuration startup, and automated tests.

The exact V6.5.4 repository was not available in this workspace. Therefore, this document does **not** claim an exact V6.5.4 line-by-line diff. V6.5.4 remains the external rollback baseline because it is the last version Drew observed placing orders.

No production Polymarket credentials were available. A real order was not submitted. This build is source-audited and test-verified, but the first Railway live order remains the final integration test.

After Version 6.5.9.5 was deployed, the live preview endpoint returned `cash_order_qty is required for market order`. Version 6.5.11 incorporates that direct production evidence by restoring `cashOrderQty` and adding an exact regression test.

## Why V6.5.6–V6.5.8 failed

1. Public fuzzy search became an execution gate.
2. The fallback expanded into hundreds of unrelated tennis contracts instead of first identifying one sporting event.
3. The candidate score could reject the actual moneyline before authenticated market validation.
4. Search/API exceptions were collapsed into generic `market not safely matched` messages.
5. A prop or exact-score result could stop or distort the fallback path.
6. Name handling failed on middle initials such as `M. H. Rehberg`.
7. Temporary failures were marked processed while the worker stayed alive.
8. In-memory processed state disappeared after a Railway restart.
9. Same-market upgrades could create another full 20% order.
10. Tests used fake SDK clients and invented payloads, then were incorrectly presented as proof of live compatibility.
11. The scanner could overcount duplicate/stale API Tennis game rows and report an impossible break lead.
12. The order path did not fully reconcile partial fills, decimal positions, or ambiguous POST outcomes.

## Replacement execution design

The rebuilt executor follows one strict sequence:

1. Require a fresh scanner `TRADE` record with two different players.
2. Treat any scanner market slug as a provisional hint only.
3. Resolve the exact event using, in order: event slug, event ID, game ID, official Search API, then a bounded date-window event query.
4. Confirm that both players belong to that event.
5. Fetch only markets belonging to that event through nested event markets, `gameId`, or `eventSlug`.
6. Retrieve each candidate market by slug from the SDK.
7. Require an active, open match-winner market with no line, exactly two structured sides, both players mapped uniquely, and one LONG plus one SHORT side.
8. Check exact-market open orders, decimal positions, and trade activity before placing anything.
9. Read the authenticated order book, `minimumTradeQty`, `orderPriceMinTickSize`, balance, and buying power.
10. Build one cash-sized 20% market order using `cashOrderQty`, explicit outcome direction, and bounded slippage.
11. Preview the exact request by passing the order parameters directly to the SDK.
12. Submit the order once. Non-idempotent order creation is never blindly retried.
13. Classify fills, partial fills, zero-fill cancellations, rejections, and pending states from the exchange response.
14. After an ambiguous timeout/connection failure, reconcile that exact market through orders, decimal positions, and trade activities. Unknown outcomes remain `PENDING` and are not automatically resubmitted.
15. Retry only explicit, safe, pre-submission failures from a fresh scanner snapshot that still qualifies.

## Official Polymarket contract comparison

| Requirement | Official contract reviewed | V6.5.11 implementation |
|---|---|---|
| Authentication | `PolymarketUS(key_id, secret_key)` with Ed25519 credentials | `PolymarketExecutionEngine.__init__` |
| Event discovery | Events support `gameId`, `eventDate`, start-time, status, category, limit and offset filters | `_matching_events`, `_event_queries` |
| Search | `search.query({query, limit, page, ...})` returns events with nested markets | `_matching_events` |
| Event-scoped markets | Markets support `gameId` and `eventSlug` filtering | `_event_markets` |
| Sports market type | Structured `sportsMarketTypeV2`, `gameId`, and `line` fields | `_market_type`, `_validated_market_side` |
| Market precision | Read `minimumTradeQty` and `orderPriceMinTickSize` from each market | `execute_trade`, `_required_decimal` |
| Cash-sized market order | The live preview endpoint requires `cashOrderQty` for market orders and supports intent or `outcomeSide` + `action`, IOC, automatic indicator, and `slippageTolerance` | `order_request` sends both direction forms, exact 20% USD `cashOrderQty`, and an up-to-three-tick adverse-price cap using the backed outcome reference, clamped at 99¢ |
| Preview | The deployed preview endpoint requires `{ "request": order }`; direct order fields return `Request is required` | `_preview` sends the required request envelope |
| Open-order filter | `orders.list({"slugs": [...]})` | `_open_orders` |
| Positions | `portfolio.positions({"market": slug, ...})`; decimal quantities are authoritative | `_positions`, `_has_position` |
| Activities | `marketSlug`, trade type, sort order and limit filters | `_activities`, `_find_trade_activity` |
| POST retry safety | Official SDK does not automatically retry non-idempotent order creation | one `orders.create` call; reconciliation on ambiguous failure |
| Order-side confirmation | Returned orders expose `intent` and/or `outcomeSide` + `action`; explicit outcome takes priority | `_validate_order_payload_contract` checks preview, creation, and status responses |
| Order lifecycle | New, pending, partial fill, filled, canceled, rejected and expired states | `_interpret_order`, `_confirm_order` |
| Real-time state | Official docs recommend private WebSocket updates over polling | V6.5.11 uses bounded REST polling; WebSocket remains a documented limitation |
| Stop-loss trigger | Current SDK order types are LIMIT and MARKET; whole-position close is exposed separately | client-side 30¢ executable-price monitor uses `orders.close_position` with no local quantity |

Official sources reviewed:

- https://github.com/Polymarket/polymarket-us-python
- https://docs.polymarket.us/api-reference/market/overview
- https://docs.polymarket.us/api-reference/sdks/python/orders
- https://docs.polymarket.us/api-reference/sdks/python/portfolio
- https://docs.polymarket.us/changelog

## File-by-file production review

| File | Lines | Review result |
|---|---:|---|
| `worker.py` | 46 | Startup/config entry point reviewed. No trading logic. Exceptions fail configuration checks clearly. |
| `streamlit_app.py` | 1,030 | Dashboard/read-only paths reviewed. Broad catches are UI containment, not order authorization. No credentials are rendered. Large file remains maintenance debt. |
| `scanner/__init__.py` | 3 | Version/export metadata only. |
| `scanner/api_tennis.py` | 306 | HTTP retries, fixture/live/stat parsing and fallback reviewed. A broad fallback catch remains intentionally non-fatal; primary errors retain context. |
| `scanner/database.py` | 132 | Local database helpers reviewed. No live-order authority. |
| `scanner/decision.py` | 95 | Decision orchestration reviewed. Strategy behavior left unchanged. |
| `scanner/discord_notifier.py` | 270 | Alert formatting reviewed. Fill wording only uses `EXECUTED`; pending/rejected states are separate. Webhook errors do not stop scanning. |
| `scanner/event_pipeline.py` | 181 | Event normalization/processing reviewed. No live-order authority. |
| `scanner/execution.py` | 17 | Compatibility re-export only. Old executor removed from this path. |
| `scanner/hard_rules.py` | 159 | Strategy hard rules reviewed and left unchanged. |
| `scanner/live_mapping.py` | 976 | Full mapping reviewed. Completed-game rows are deduplicated and reconciled to the current set score, preventing impossible break counts from duplicate/stale API rows. Large function remains maintenance debt. |
| `scanner/live_scan.py` | 221 | Live scan orchestration reviewed. Errors are surfaced without stopping the full worker. |
| `scanner/market_validation.py` | 319 | Public informational market validation reviewed. It is no longer the final live-execution authority. |
| `scanner/models.py` | 75 | Data models reviewed. No live-order authority. |
| `scanner/polymarket.py` | 1,241 | Legacy/public lookup reviewed. It can still populate informational Discord fields, but it cannot approve, reject, map, or submit a live order. Its size and old fuzzy matcher are maintenance debt and should eventually be isolated further. |
| `scanner/polymarket_executor.py` | 1,955 | Rebuilt execution authority reviewed line by line. Event resolution, strict market validation, order construction, precision, idempotency, reconciliation, and status interpretation are covered by focused tests. The 452-line `execute_trade` method should be split in a future cleanup, but its current branches are tested. |
| `scanner/reconciliation.py` | 535 | Paper/outcome reconciliation reviewed. No live order submission. Large function remains maintenance debt. |
| `scanner/scoring.py` | 251 | Stability scoring reviewed and left unchanged. |
| `scanner/supabase_dashboard.py` | 167 | Read-only dashboard client reviewed. GET-only retry behavior. |
| `scanner/supabase_store.py` | 305 | Storage retry/error handling reviewed. No credential logging found. |
| `scanner/worker_runtime.py` | 1,261 | Execution queue reviewed. Retryable signals require a fresh qualifying snapshot; terminal, submitted, or filled signals are suppressed; signal key does not change between INITIAL/UPGRADE labels. Same-market upgrades therefore cannot stack another full 20% order. |

## Static review results

- Python syntax/AST parsing: passed for every production and test file.
- Bare `except:` blocks: none.
- `eval`/`exec`: none.
- `TODO`, `FIXME`, `HACK`, or `XXX` markers in production Python: none.
- Mutable function-default findings: none found in the AST review.
- Compilation: passed.
- Secret scan: no live `.env`, API key, secret key, Discord webhook, or nested ZIP included.
- Known maintainability findings: six production functions exceed 120 lines. These are documented debt, not hidden as proof of simplicity.

## Focused failure cases covered

- `J. Mensik vs T. Svajda` with moneyline, spread, and total in one event.
- `A. Mannarino vs L. Tien`.
- `M. H. Rehberg vs S. Travaglia` with middle initials/full-name mapping.
- `T. Skatov vs T. Faurel` with an exact-score result appearing before the moneyline.
- Invalid scanner slug leading to the same event's valid moneyline.
- Generic title with structured player sides and no explicit market-type field.
- Spread, total, exact score, set winner, straight sets, tie-break, number-of-sets, and score props rejected.
- Reversed names, initials, middle initials, accents, surname-first names, boolean LONG flags, and YES/NO side flags.
- Explicit SHORT/NO request contract (`ORDER_INTENT_BUY_SHORT` + `OUTCOME_SIDE_NO` + `ORDER_ACTION_BUY`).
- Preview-side mismatch, intent/outcome conflict, and wrong-side create response blocked before any success report.
- Wrong event/date ambiguity rejected rather than guessed.
- Missing minimum quantity/tick rejected before order creation.
- Half-cent tick and decimal minimum quantity handling.
- Existing open order, decimal position, or prior trade activity blocks duplicates.
- Deprecated rounded position `0` with nonzero `netPositionDecimal` still blocks a duplicate.
- Zero-fill canceled/rejected IOC may retry; partial fill never retries.
- Timeout after create reconciles orders, positions, and activities.
- Explicit HTTP 429 create rejection retries only from a fresh qualifying scanner record.
- Authentication/bad-request errors retain the actual failure stage.
- Duplicate API Tennis game rows cannot fabricate a two-break lead at a 1–0 set score.

## Final verification outcome

- Full automated suite: **168 tests passed** in the source tree after the 20% sizing and 30¢ stop-loss additions.
- The release ZIP is re-tested after clean extraction before delivery.
- Full Python compilation: passed in the source tree and clean extraction.
- Dry-run Railway configuration startup: passed with Version `6.5.11`, cash-sized 20% sizing, active 30¢ stop monitoring, unlimited distinct markets, and same-market upgrades disabled.
- AST/static scan: no syntax failures, bare `except:`, `eval`, `exec`, mutable collection defaults, or production TODO/FIXME/HACK markers.
- Package scan: no live `.env`, credentials, private keys, webhook URLs, caches, compiled Python files, or nested ZIPs included.
- No live-money order was submitted.

## Remaining limitations and release risk

1. **No live credential test:** the actual authenticated POST was not run here.
2. **No exact V6.5.4 diff:** the V6.5.4 ZIP was unavailable.
3. **No private WebSocket listener:** the executor uses bounded REST polling and next-cycle exchange reconciliation. The official docs prefer private WebSocket order updates for real-time lifecycle tracking.
4. **No local persistent execution ledger:** restart safety depends on exact-market exchange state (open orders, decimal positions and trade activities). That is materially safer than memory-only deduplication but is not a mathematically perfect idempotency key if the exchange is temporarily inconsistent immediately after an ambiguous POST.
5. **SDK runtime package unavailable in this build container:** the internal package index did not provide `polymarket-us==0.1.2`, and outbound Git access was blocked. The SDK transport and 0.1.2 source/types were reviewed, and the package remains pinned to that version. The current REST contract adds `outcomeSide` + `action`; the SDK order resource forwards the supplied dictionary unchanged, but the real package could not be imported here.
6. **Legacy code size:** `scanner/polymarket.py`, `scanner/live_mapping.py`, `scanner/worker_runtime.py`, and the new executor contain long functions. They passed the current tests but remain future maintenance risk.
7. **First live order is the final acceptance gate:** do not call the release live-proven until Railway shows the exact event, moneyline type, side mapping, order ID, and confirmed exchange state.

## Release decision

V6.5.11 is materially different from the failed V6.5.6–V6.5.8 matcher and is suitable for a controlled Railway integration test. It is **not** described as guaranteed or live-proven.

If the first live trade cannot resolve a normal active ATP moneyline, maps the wrong player, selects a prop, submits a duplicate, or reports a fill without exchange evidence, disable execution and restore the untouched V6.5.4 deployment.
