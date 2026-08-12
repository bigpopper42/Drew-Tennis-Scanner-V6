# Automation Roadmap

## Completed through Version 6.5.13

- API Tennis-first live discovery and automated decision-tree scanning
- Polymarket US event-first moneyline resolution
- live LONG/YES and SHORT/NO execution path
- exact **20%** account-balance entry sizing
- authenticated order preview, duplicate-position checks, and Discord execution reporting
- Cloudflare/rate-limit protection
- cash-sized market entry orders with bounded slippage and explicit YES/NO outcome validation
- active client-side **30¢ backed-outcome stop-loss** for open ATP positions
- Supabase cycle, heartbeat, scan, and dashboard storage

## Active safety behavior

- Monitor the exact backed outcome on each worker cycle.
- Trigger a close when the executable backed-outcome price reaches **30¢ or lower**.
- Use a fixed 30¢ price trigger, not a percentage-loss calculation.
- LONG uses the executable YES bid; SHORT/NO uses `1 - best YES offer`.
- Close through Polymarket's dedicated whole-position close endpoint so stale local quantity cannot reverse the position.
- Re-read the authenticated portfolio each cycle, including after worker restarts.
- Report exit confirmation, unfilled close, pending status, rejection, and monitoring errors through Discord.

## Later milestones

1. Collect full LONG + SHORT live execution data.
2. Add liquidity-aware sizing before individual orders become large enough to move through multiple price levels.
3. Add complete realized P&L and bankroll analytics.
4. Review whether 20% sizing and the 30¢ stop are optimal after a meaningful trade sample.
5. Analyze performance by side, entry price, score state, tournament level, and scanner rule.

- Version 6.5.13: one-break maturity gate (4 games unbroken / 5 games after a break), 20% sizing, and 15-second cycle.
