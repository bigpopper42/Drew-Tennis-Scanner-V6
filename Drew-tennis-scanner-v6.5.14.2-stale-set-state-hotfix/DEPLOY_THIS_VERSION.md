# Deploy Version 6.5.14.2

Deploy the flat-root repository to Railway and preserve the previous deployment as the rollback point.

Confirm startup reports Version `6.5.14.2`. The production worker remains locked to a 15-second cycle.

Live execution targets:

- one-break trade: 15% total exposure
- two+ break trade: 25% total exposure
- one-break position upgraded to two+ breaks: add only enough cash to reach 25%
- backed-outcome stop: 35¢

Legacy `EXECUTION_BANKROLL_PCT` and `SCAN_INTERVAL_SECONDS` values are intentionally ignored for these locked production values.
