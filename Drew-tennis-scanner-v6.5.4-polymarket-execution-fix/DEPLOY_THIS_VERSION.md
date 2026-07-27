# Deploy Version 6.5.4 Polymarket US Execution

This ZIP is flat-rooted. Opening it shows `worker.py`, `requirements.txt`, `railway.toml`, `scanner/`, `tests/`, and the documentation files directly, with no extra enclosing folder.

1. Replace the current GitHub repository contents with this ZIP's contents.
2. Commit and push to the repository already connected to Railway.
3. Redeploy Railway.
4. Confirm the startup log and Discord connection message report Version `6.5.4` and `Polymarket execution: LIVE`.

Keep all existing Railway variables unchanged. Do not paste credentials into code, GitHub, or chat.

No Supabase migration is required for Version 6.5.4.

The code-level fix is complete and the full test suite passes. A new live Railway trade signal is still required for final production validation.
