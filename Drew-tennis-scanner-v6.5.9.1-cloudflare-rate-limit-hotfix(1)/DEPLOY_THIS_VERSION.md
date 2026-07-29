# Deploy Version 6.5.9.1

This is a complete flat-root repository replacement. Opening the ZIP shows `worker.py`, `requirements.txt`, `railway.toml`, `scanner/`, `tests/`, and the setup files directly.

1. Preserve the last known rollback ZIP or Git commit before replacing anything.
2. Replace the current GitHub repository contents with this ZIP's contents.
3. Commit and push.
4. Redeploy Railway.
5. Confirm the startup log and Discord connection message report Version `6.5.9.1` and `Polymarket execution: LIVE`.

No Supabase migration is required.

Version 6.5.9.1 locks sizing at 20% and ignores legacy `EXECUTION_BANKROLL_PCT`, `EXECUTION_MAX_ORDER_USD`, and execution confidence values. The executor no longer uses a public confidence threshold to authorize or reject a live market.


## Rate-limit behavior

Version 6.5.9.1 spaces Polymarket SDK calls and retries only definite Cloudflare 1015 or HTTP 429 edge throttles. Keep Railway at one active worker replica per API key.
