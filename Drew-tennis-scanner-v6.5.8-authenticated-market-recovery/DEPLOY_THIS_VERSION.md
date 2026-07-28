# Deploy Version 6.5.8

This ZIP has a flat repository root. Opening it shows `worker.py`, `requirements.txt`, `railway.toml`, `scanner/`, `tests/`, and the documentation files directly.

1. Replace the current GitHub repository contents with this ZIP's contents.
2. Commit and push to the repository connected to Railway.
3. Redeploy Railway.
4. Confirm the startup log and Discord connection message report Version `6.5.8` and `Polymarket execution: LIVE`.

No Supabase migration is required.

Version 6.5.8 locks live sizing at 20% and removes the scanner's fixed-dollar maximum cap. Existing `EXECUTION_BANKROLL_PCT` and `EXECUTION_MAX_ORDER_USD` Railway variables may remain because this version ignores them.
