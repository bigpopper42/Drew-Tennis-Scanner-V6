# Deploy Version 6.5.9.6

1. Replace the repository contents with this ZIP while preserving the existing `.git` folder if using a local clone.
2. Commit every replacement file.
3. Push to GitHub.
4. Redeploy the existing Railway service.
5. Confirm startup reports Version `6.5.9.6` and `Polymarket execution: LIVE`.

## Entry behavior

Version 6.5.9.6 submits a cash-sized market order equal to exactly 20% of authenticated balance, limited by buying power. The submitted market-order field is `cashOrderQty`, as required by the live preview endpoint.

SHORT/NO still sends `ORDER_INTENT_BUY_SHORT`, `OUTCOME_SIDE_NO`, and `ORDER_ACTION_BUY`. LONG/YES sends the matching LONG and YES fields. Both use immediate-or-cancel behavior and a three-tick slippage cap.

Discord now labels the calculated contract count as `Estimated contracts`; the exchange calculates the actual filled quantity from `cashOrderQty` and the execution price.

The proposed emergency exit remains a fixed **40¢ backed-outcome trigger**, but automatic stop-loss execution is not active in Version 6.5.9.6.
