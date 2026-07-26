# Version 6.5.1 Build Notes

- Fixed Polymarket US tennis total-games markets being misclassified as
  match-winner markets when both player names appeared in the contract.
- Added a regression test for
  `tsc-atp-alevuk-alebol-2026-07-26-tg-27pt5`.
- Scanner decision rules, 10% execution sizing, and all other safeguards are
  unchanged.

## Added

- `scanner/execution.py` using the official Polymarket US Python SDK
- guarded 10%-of-balance live market orders
- order preview, one-position limit, market/name/state checks, price limits,
  buying-power checks, and duplicate prevention
- Discord confirmations for placed, blocked, and failed executions
- `POLYMARKET_EXECUTION_SETUP.md`
- execution-specific regression tests with fake API clients

## Unchanged

- Drew's decision tree
- qualification thresholds
- Stability Score formula
- scanner scoring tiers
- Supabase schema

## Validation

- `python -m pytest -q`: 53 passed
- Python compilation check passed
