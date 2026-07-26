# Deploy Version 6.5 Polymarket US Execution

This archive is flat-rooted. The GitHub repository homepage must show `worker.py`, `requirements.txt`, `railway.toml`, `scanner/`, and `sql/` directly at the top level.

1. Replace the current GitHub repository contents with this archive's contents.
2. Commit and push the files to the same repository already connected to Railway.
3. Keep the current Discord webhook variables.
4. Add the Polymarket US variables listed in `POLYMARKET_EXECUTION_SETUP.md`.
5. The required live values are:

```text
POLYMARKET_KEY_ID=YOUR_KEY_ID
POLYMARKET_SECRET_KEY=YOUR_SECRET_KEY
POLYMARKET_EXECUTION_ENABLED=true
```

6. Keep every existing Railway variable, including the API Tennis, Supabase,
   Discord, and `SAVE_ALL_SCANS` values.
7. Deploy the staged Railway changes.
8. Confirm Railway logs show `version: 6.5`.
9. Confirm Discord reports `Polymarket execution: LIVE`.

No Supabase migration is required for Version 6.5.
