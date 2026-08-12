# SHORT/NO Execution Notes — Version 6.5.14

The existing SHORT/NO direction contract is preserved: `ORDER_INTENT_BUY_SHORT`, `OUTCOME_SIDE_NO`, and `ORDER_ACTION_BUY` are sent together, with cash-sized market orders and backed-outcome slippage reference.

V6.5.14.1 does not rewrite the SHORT/NO mapping. It changes only risk sizing around approved trades: one-break target 15%, two+ break target 25%, same-position upgrades by difference, and a 35¢ stop trigger.
