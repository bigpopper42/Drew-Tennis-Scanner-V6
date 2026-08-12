# 35¢ Stop-Loss Implementation — Version 6.5.14

The worker monitors authenticated ATP positions each cycle and closes a position when the executable price of the backed outcome is **35¢ or lower**. This is a fixed contract-price trigger, not a percentage-loss calculation.

YES positions use the executable YES bid. NO positions use the complementary executable NO value derived from the YES offer. The whole-position `close_position` endpoint is used so the close cannot intentionally increase or reverse exposure.

The monitor is client-side and runs on the locked 15-second worker cycle, so 35¢ is a trigger rather than a guaranteed fill price. Railway must be running and Polymarket must be reachable.
