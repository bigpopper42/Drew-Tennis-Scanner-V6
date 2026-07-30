# Version 6.5.9.4 Build Notes

## SHORT/NO zero-fill correction

The Matsuoka–Mochizuki order reached Polymarket as an accepted SHORT/NO order and received order ID `BJ1MRKCF49NE`, but it finished in `ORDER_STATE_EXPIRED` with zero quantity filled. That is different from a wrong-side submission rejection.

Version 6.5.9.4 fixes a preview-envelope regression introduced in 6.5.9.3.
The deployed preview endpoint requires `{"request": <order>}`; sending the
order fields directly returns `Request is required` before submission.

Version 6.5.9.4 changes entry execution as follows:

1. Preview calls now send the order parameters directly, matching the installed Polymarket Python SDK contract.
2. Entry requests now use an explicit price-capped IOC limit order rather than a cash market order.
3. LONG/YES orders use the best executable YES offer plus the configured one-tick allowance.
4. SHORT/NO orders convert the allowed NO price back into the required YES-reference limit price.
5. Quantity is rounded down at the worst allowed player price, keeping maximum order cost at or below the exact 20% stake.
6. Every request still sends both direction representations:
   - LONG: `ORDER_INTENT_BUY_LONG`, `OUTCOME_SIDE_YES`, `ORDER_ACTION_BUY`
   - SHORT: `ORDER_INTENT_BUY_SHORT`, `OUTCOME_SIDE_NO`, `ORDER_ACTION_BUY`
7. Preview, create, and final status payloads are still checked for wrong-side or contradictory outcome fields.

Example from the reported failure:

- Backed NO price: 87¢
- One-tick maximum player price: 88¢
- Required YES-reference limit price: 12¢
- Account balance: $67.67
- 20% stake: $13.53
- Maximum quantity: 15.37 contracts
- Maximum calculated spend: no more than $13.53

## Corrected expired-order reporting

`ORD_REJECT_REASON_EXCHANGE_OPTION` is the exchange enum's default value and can appear on a non-rejected response. Version 6.5.9.4 no longer displays it as the cause unless the response actually contains a rejected order state or execution type.

A zero-fill IOC expiry is now reported as:

> IOC order expired or canceled without a fill because no executable quantity remained at the allowed price; no position was opened.

It remains retryable only from a fresh qualifying scanner snapshot. The bot does not blindly duplicate an order after an ambiguous submission.

## Future 40¢ emergency exit

The planned stop rule has been updated from 45¢ to a fixed **40¢ backed-outcome trigger**. It is recorded in `AUTOMATION_ROADMAP.md` but is not active in this build.

## Preserved behavior

- Exact 20% sizing
- Event-first market resolution
- Moneyline-only validation
- authenticated player-side mapping
- open-order, position, and activity duplicate protection
- Cloudflare 1015 and HTTP 429 handling
- Railway, Discord, Supabase, and Streamlit integration

## Verification standard

The final package must pass the complete automated test suite and Python compilation both in the source directory and after fresh extraction of the final ZIP.

No live-money order is submitted during local verification because production credentials are not included.
