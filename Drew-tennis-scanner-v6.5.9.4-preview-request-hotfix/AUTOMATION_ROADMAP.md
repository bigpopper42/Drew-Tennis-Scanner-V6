# Automation Roadmap

## Completed through Version 6.5.9.4

- API Tennis-first live discovery and automated decision-tree scanning
- Polymarket US event-first moneyline resolution
- live LONG/YES and SHORT/NO execution
- exact 20% account-balance sizing
- authenticated order preview, duplicate-position checks, and Discord execution reporting
- Cloudflare/rate-limit protection
- price-capped IOC entry orders with explicit YES/NO outcome validation
- Supabase cycle, heartbeat, scan, and dashboard storage

## Next safety milestone: 40¢ emergency exit

The next major execution feature is automatic downside protection after an entry fills.

Planned rule:

- Monitor the price of the exact outcome that the scanner backed.
- Trigger an emergency close when that backed outcome reaches **40¢ or lower**.
- The trigger is a fixed backed-outcome price of 40¢, not a 40% loss calculation.
- Cover only the quantity actually filled by the entry order.
- Correctly invert YES-reference pricing when the held position is SHORT/NO.
- Prevent an exit order from opening an accidental opposite-side position.
- Cancel or retire the protective order after the position resolves or is otherwise closed.
- Report stop placement, activation, partial fill, full fill, and failure through Discord.
- Backtest and dry-run the behavior before allowing live exits.

**The 40¢ emergency exit is documented here but is not active in Version 6.5.9.4.**

## Later milestones

1. Add liquidity-aware sizing before individual orders become large enough to move through multiple price levels.
2. Add complete realized P&L and bankroll analytics.
3. Review position sizing as bankroll grows.
4. Finish long-run performance analysis by price, score state, tournament level, and rule.
