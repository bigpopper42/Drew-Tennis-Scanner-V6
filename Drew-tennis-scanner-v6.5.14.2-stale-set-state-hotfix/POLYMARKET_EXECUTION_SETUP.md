# Polymarket US Live Execution Setup — Version 6.5.14.2

## Entry sizing

Production sizing is tiered target exposure, not a flat stake:

- one-break approved trade: **15% total bankroll exposure**
- two-or-more-break approved trade: **25% total bankroll exposure**
- existing one-break position upgraded to two+ breaks: buy only the difference needed to reach 25%

Market orders continue to use `cashOrderQty`, explicit YES/NO direction, IOC execution, and bounded slippage. Pending orders and unreconciled fills still block duplicate submission.

## 35¢ stop loss

The worker monitors authenticated ATP positions every locked 15-second cycle. When the executable backed-outcome price reaches **35¢ or lower**, it uses Polymarket's whole-position close endpoint. The stop is client-side, so 35¢ is a trigger rather than a guaranteed fill.
