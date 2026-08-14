# Polymarket Execution Audit — Version 6.5.14.2

The live execution authority is `scanner/polymarket_executor.py`. `scanner/execution.py` remains a compatibility re-export.

V6.5.14.2 preserves the validated cash market-order path and explicit YES/NO contract mapping. The material change is target-exposure sizing:

1. one-break signal → 15% target
2. two+ break signal without a position → 25% target
3. live same-side one-break position upgraded to two+ breaks → add only the difference to 25%
4. pending order → block
5. filled order without reconciled position → block
6. opposite-side position → block
7. position already at/above target → block

The client-side backed-outcome stop trigger is 35¢ and the production cycle remains 15 seconds.
