# Deploy Version 6.1 Diagnostic Fix

This archive is intentionally flat-rooted. After uploading it to GitHub, the repository homepage must show `worker.py`, `requirements.txt`, `railway.toml`, `scanner/`, and `sql/` directly at the top level.

1. Replace the current GitHub repository contents with this archive's contents.
2. Keep the existing Railway variables and keep `SAVE_ALL_SCANS=true`.
3. Redeploy Railway.
4. Confirm the logs show `version: 6.1` and `storage_mode: all_player_evaluations` in `worker_ready`.
5. After one scan cycle, run `sql/diagnostic_query.sql` in Supabase.

No Supabase schema migration is required if the Version 6.0 schema was already installed.
