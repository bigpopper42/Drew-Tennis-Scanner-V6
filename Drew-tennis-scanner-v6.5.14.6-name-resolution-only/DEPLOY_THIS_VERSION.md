# Deploy v6.5.14.4: local SQLite, no external database

Upgrade the existing scanner Railway service using **the contents** of this ZIP at the repository root. Preserve the current v6.5.14.3 deployment as a rollback. Delete the old Supabase Railway variables. Keep API Tennis, Discord and Polymarket credentials/configuration unchanged.

For durable local diagnostics, mount a Railway Volume at `/app/data` and set `SCANNER_DATA_DIR=/app/data`. Otherwise the worker continues with an ephemeral database; only history is at risk, not live scanning.

Verify `worker_ready`, version `6.5.14.4`, 15-second cycles, and Discord notifications. Confirm trading and exchange state under live conditions before calling the deployment accepted. No access to Railway has been performed in this task.

Locked trading: one-break 15%, two-break 25%, 35¢ backed-side stop, 15-second scans; unchanged from v6.5.14.3.
