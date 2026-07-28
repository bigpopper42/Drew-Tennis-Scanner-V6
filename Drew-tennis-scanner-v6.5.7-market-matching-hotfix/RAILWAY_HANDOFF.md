# Railway Handoff — Version 6.5.7

Version 6.5.7 keeps the scanner decision tree unchanged and completes the live execution fixes:

- exact-score search hits cannot stop the lookup before the real moneyline is found;
- generic current tennis moneylines can be validated from two named opposite LONG/SHORT player contracts even when market-type text is omitted;
- match-winner moneyline only;
- exact-score and other props rejected;
- authenticated live YES/NO mapping only;
- 20% live sizing with no fixed scanner dollar cap;
- multiple distinct positions allowed;
- scanner-approved same-market upgrades allowed;
- unchanged duplicate signals and unfinished same-market orders blocked;
- order status queried after submission;
- Discord success shown only for a confirmed fill or partial fill.

Deploy the flat-root repository to the existing Railway service. No database migration is required. Keep `POLYMARKET_EXECUTION_ENABLED=true` for live orders or set it to `false` for the emergency stop.
