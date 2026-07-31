# Version 6.5.9.5 Build Notes

Version 6.5.9.5 targets the remaining live SHORT/NO fill failure while leaving the tennis scanner rules and locked 20% bankroll sizing unchanged.

## Exact changes

1. Replaced the SHORT/NO IOC limit entry with an exchange-native market order.
2. Removed `cashOrderQty`; market orders now submit the official decimal contract `quantity` field.
3. Preserved all three explicit direction fields: `ORDER_INTENT_BUY_SHORT`, `OUTCOME_SIDE_NO`, and `ORDER_ACTION_BUY`.
4. Preserved the required preview `request` envelope used by the deployed `polymarket-us==0.1.2` integration.
5. Added a three-tick `slippageTolerance` cap using Polymarket's required YES/long reference price.
6. Sized quantity at the worst allowed backed-outcome price, preventing the order from spending above the locked 20% stake when the slippage cap is honored.
7. Added Discord execution telemetry: order type, quantity, YES bid/ask, backed price, YES reference, maximum backed price, slippage ticks, and failure stage.
8. Kept duplicate-order, existing-position, uncertain-POST, side-validation, and exact-moneyline protections unchanged.
9. Kept the planned 40¢ stop loss inactive.

## Why this is a meaningful next stage

- V6.5.9.2 reached the exchange with an undocumented cash-quantity market shape.
- V6.5.9.4 reached the exchange with an explicit quantity but used a synthetic IOC limit that expired unfilled.
- V6.5.9.5 uses the supported market-order quantity contract and retains bounded slippage.

If the next SHORT/NO still fails, the added Discord fields will identify whether it failed during preview, submission, or final exchange status and will show the exact book and converted pricing used.

## Verification

- Full test suite: 161 passing tests.
- Exact 76¢ SHORT/NO live scenario covered.
- Preview-envelope regression covered.
- SHORT/NO side-conflict protections covered.
- Discord diagnostic output covered.
- Python compilation passed.
