# Version 6.5.3 Build Notes

## 6.5.3 authenticated execution mapping fix

- Removes the premature discovery-side rejection before authenticated market
  retrieval.
- Treats live `marketSides[].team` and `marketSides[].long` as authoritative.
- Normalizes accents, punctuation, capitalization, and whitespace.
- Safely matches exact names and full-first-name/initial variants only when
  surnames agree.
- Requires the backed player and opponent to map uniquely to different sides.
- Keeps ambiguous mappings rejected without assuming the first player is YES.
- Changes the Discord sizing line to `Live order size: 10% of authenticated
  balance`.

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

- `python -m pytest -q`: 61 passed
- Python compilation check passed
