# Version 6.4 Build Notes

## Added

- `scanner/discord_notifier.py`
- Discord webhook configuration through Railway environment variables
- one startup connection confirmation
- one alert when a player first becomes a `TRADE`
- one additional alert when the recommendation upgrades to a higher position-size tier
- in-memory retry queue for temporary Discord failures
- safe `allowed_mentions` payload so player names or text cannot trigger Discord mentions
- Arizona-local alert timestamps through the existing `TIMEZONE` setting
- six Discord-specific regression tests

## Unchanged

- Drew's decision tree
- qualification thresholds
- Stability Score formula
- position-size bands
- Supabase schema
- dashboard behavior
- Polymarket informational-only behavior

## Validation

- `python -m pytest -q`: 44 passed
- Python compilation check passed
