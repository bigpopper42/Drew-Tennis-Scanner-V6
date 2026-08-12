# Drew Tennis Scanner Version 6.5.13

Version 6.5.13 keeps the fresh-break consolidation protection and replaces the qualifier top-150-only rule with a **tiered backed-player ranking gate**: top 150 can face anyone; 151-200 require opponent #450+; 201-250 require opponent #750+; 251+ are blocked. Live sizing remains **20%**, the worker remains locked to **15-second cycles**, and the existing 30¢ client-side stop-loss and V6.5.9.7 SHORT/NO entry path remain active.

## Scanner hard-rule change

For a backed player with exactly **one break of lead** in the current set:

- If the backed player has **not been broken** in the current set, they must have won at least **4 games** in that set before the match can become tradeable.
- If the backed player has been broken **at least once**, they must have won at least **5 games** in that set before the match can become tradeable.
- The existing service, point-score/consolidation, closing-set, tiebreak, volatility, and stability requirements still apply after this gate.
- Two-break leads are not delayed by this new maturity rule. Existing break-volatility rules still apply.

This specifically blocks early one-break states created in the opening games from qualifying solely because the lead was consolidated.

## Live execution

- LONG/YES: `ORDER_INTENT_BUY_LONG`, `OUTCOME_SIDE_YES`, `ORDER_ACTION_BUY`.
- SHORT/NO: `ORDER_INTENT_BUY_SHORT`, `OUTCOME_SIDE_NO`, `ORDER_ACTION_BUY`.
- Market entries use `cashOrderQty` equal to exactly **20%** of authenticated balance, limited by buying power.
- IOC execution and bounded entry slippage remain unchanged.
- Duplicate same-market exposure remains blocked.

## 30¢ stop-loss and 15-second cycle

- Stop trigger remains a fixed **30¢ backed-outcome executable price**.
- LONG/YES uses best YES bid.
- SHORT/NO uses executable NO bid (`1 - best YES offer`).
- Stop exits use the dedicated position-close path.
- The production worker cycle is locked to **15 seconds**, so stop monitoring and live scanning are evaluated about twice as often as V6.5.10. If a cycle itself takes longer than 15 seconds, the next cycle starts immediately after the current one completes.
- The stop is client-side, so Railway must be running and a 30¢ trigger does not guarantee a 30¢ fill.

## Deployment

1. Replace the GitHub repository contents with this archive.
2. Commit and push.
3. Redeploy Railway.
4. Confirm startup reports Version `6.5.13`, scan interval `15`, execution sizing `20%`, and stop trigger `30¢`.
5. No Supabase migration is required.
