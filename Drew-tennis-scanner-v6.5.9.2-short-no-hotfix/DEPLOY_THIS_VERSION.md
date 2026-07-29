# Deploy Version 6.5.9.2

This is a complete flat-root repository replacement. Opening the ZIP shows `worker.py`, `requirements.txt`, `railway.toml`, `scanner/`, `tests/`, and the setup files directly.

1. Preserve the last known rollback ZIP or Git commit before replacing anything.
2. Replace the current GitHub repository contents with this ZIP's contents.
3. Commit and push.
4. Redeploy Railway.
5. Confirm the startup log and Discord connection message report Version `6.5.9.2` and `Polymarket execution: LIVE`.

No Supabase migration is required.

Version 6.5.9.2 locks sizing at 20% and ignores legacy `EXECUTION_BANKROLL_PCT`, `EXECUTION_MAX_ORDER_USD`, and execution confidence values. The executor no longer uses a public confidence threshold to authorize or reject a live market.


## Rate-limit behavior

Version 6.5.9.2 spaces Polymarket SDK calls and retries only definite Cloudflare 1015 or HTTP 429 edge throttles. Keep Railway at one active worker replica per API key.

## SHORT/NO behavior

Version 6.5.9.2 explicitly sends `OUTCOME_SIDE_NO` + `ORDER_ACTION_BUY` alongside `ORDER_INTENT_BUY_SHORT` whenever the backed player is the authenticated SHORT/NO team. Railway does not need any new environment variable for this change.
