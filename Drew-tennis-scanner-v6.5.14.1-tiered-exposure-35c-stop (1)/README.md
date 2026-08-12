# Drew Tennis Scanner Version 6.5.14

V6.5.14.1 preserves the V6.5.13 scanner hardening and adds tiered target exposure for live Polymarket execution.

## Risk model

- One-break approved setups target **15%** of bankroll.
- Two-or-more-break approved setups target **25%** of bankroll.
- An existing one-break position that later qualifies at two+ breaks is **upgraded only by the difference** needed to reach 25%; it is not rejected merely because a position already exists.
- Repeat signals cannot stack the same position above the target.
- The backed-outcome client-side stop is **35¢**.
- Worker cycle remains **15 seconds**.

## Scanner protections retained

The minimum-game maturity, 40-0/30-0 fresh-break consolidation rules, qualifier ranking tiers, ATP scope, market matching, LONG/YES and SHORT/NO execution logic, Discord notifications, and duplicate/pending-order safeguards remain active.

See `BUILD_NOTES.md` and `DEPLOY_THIS_VERSION.md` for the exact release behavior.
