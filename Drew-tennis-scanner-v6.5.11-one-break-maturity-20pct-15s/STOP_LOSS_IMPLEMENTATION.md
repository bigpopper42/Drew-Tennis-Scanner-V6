# 30¢ Stop-Loss Implementation — Version 6.5.11

## Rule

Close an open ATP position when the **executable price of the backed outcome is 30¢ or lower**. This is a fixed contract-price trigger, not a 30% loss from entry.

## Price used

- LONG/YES: best executable YES bid.
- SHORT/NO: executable NO bid = `1 - best YES offer`.
- Last-trade price is not used as the trigger because it may be stale or non-executable.

## Exit method

The current Polymarket US SDK exposes LIMIT and MARKET order types, not a native STOP order. The worker therefore monitors positions client-side and calls `orders.close_position` when the stop triggers.

`close_position` is used specifically because it targets the existing position and does not require a locally supplied quantity. That avoids a stale quantity accidentally opening an opposite-side position after a partial fill or concurrent position change.

## Timing

The monitor runs once per worker cycle before new entry attempts. Default `SCAN_INTERVAL_SECONDS` is 30, so the stop is checked about every 15 seconds under the default deployment. It is not guaranteed to execute at exactly 30¢; a fast tennis market may move below the trigger between checks or while the close is routing.

## Restart behavior and scope

The monitor reads the authenticated Polymarket portfolio every cycle and manages open ATP market slugs. This means protection resumes after a Railway restart without relying on in-memory state. It also means a manually opened ATP position in the same account is subject to the same 30¢ rule. Non-ATP positions are ignored.

## Discord statuses

- `EXITED`: close fill confirmed.
- `UNFILLED`: close attempted but no quantity filled; remaining position is checked next cycle.
- `PENDING`: close order may exist but final status is unresolved; next cycle reconciles the portfolio first.
- `REJECTED`: Polymarket rejected the close.
- `FAILED`: price/portfolio/API monitoring failed.
