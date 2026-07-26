# Version 6.5 Build Notes

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
