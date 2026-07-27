# Version 6.5.2 Build Notes

## 6.5.2 execution mapping hotfix

- Reads current Polymarket US sports competitors from `teams`.
- Reads current long/short player identity from `marketSides[].team` and
  `marketSides[].long`.
- Retains legacy `participants`, `sides`, and `outcomes` compatibility.
- Adds an explicit `Trade: <player>` line to every Discord scanner alert.
- Adds regression coverage for S. Kwon vs E. Winter and A. Mayo vs
  R. Pascual Ferra.

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
