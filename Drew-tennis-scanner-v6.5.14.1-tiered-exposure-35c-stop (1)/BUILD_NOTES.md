# Version 6.5.14 Build Notes

Version 6.5.14 changes live risk management from one flat stake to target exposure tiers while preserving the V6.5.13 scanner hard gates.

## Live target exposure

- One-break approved trade: 15% total bankroll exposure.
- Two-or-more-break approved trade: 25% total bankroll exposure.
- If no position exists and a two-break signal appears, the first order targets 25%.
- If a live same-side one-break position later upgrades to two+ breaks, the executor buys only the difference required to reach 25%.
- Repeat two-break signals cannot stack exposure above the 25% target.
- A one-break repeat signal never adds to an existing position.
- An opposite-side position blocks any upgrade.
- Pending orders and filled orders whose live portfolio position has not reconciled still block submission.

The add-on calculation uses the existing position cost basis plus remaining cash to reconstruct the bankroll basis for that market. Example: $15 cost basis + $85 remaining cash = $100 bankroll basis; the 25% target is $25, so the upgrade submits $10.

## Stop loss

The client-side backed-outcome stop trigger is now 35¢. It still uses Polymarket's whole-position close endpoint and is checked on the 15-second worker cycle.

## Preserved scanner protection

- One-break trades require at least 4 current-set games if unbroken.
- If broken in the current set, one-break trades require at least 5 games.
- Fresh break at 4 requires reaching 40-0 while serving for game five.
- Fresh break at 5 requires reaching 30-0 while serving for game six.
- Qualifier ranking tiers from V6.5.12.2 remain in place.

## Verification

The suite includes direct tests for fresh 15% one-break entries, fresh 25% two-break entries, 15%→25% upgrades, legacy 20%→25% upgrades, no stacking above 25%, opposite-side protection, and the 35¢ stop.
