# Drew Tennis Scanner — v6.5.14.4 (Supabase removed)

This is the v6.5.14.3 production logic with **Supabase integration removed** and replaced with optional local SQLite diagnostic persistence.

**The trading logic was not modified:** API Tennis evaluation, market selection, Polymarket order/exposure logic, Discord execution alerts and the client-side 35¢ stop-loss monitor are unchanged from the August 15 v6.5.14.3 source. The production scan interval remains 15 seconds; target exposure stays 15% for one break and 25% for two or more breaks. Existing live-trading variables are unchanged.

## Deployment on Railway

1. Keep a copy of your *working* v6.5.14.3 deployment as your rollback baseline.
2. Replace **repository-root contents** with this ZIP; keep your existing `API_TENNIS_KEY`, Polymarket US credentials, Discord webhook and trading variables unchanged.
3. Remove the old Supabase variables from Railway. They are **not used** by this release. Do **not** copy any credentials into this ZIP.
4. **Recommended:** Add a Railway persistent Volume, mounted at `/app/data`, and set `SCANNER_DATA_DIR=/app/data`. If no persistent volume is configured, local database history may disappear on deployments/restarts. This never blocks trading.
5. Deploy and verify the startup log says version **6.5.14.4**, `worker_ready`, and every subsequent `cycle_complete`. Confirm Discord startup message and qualified trade/stop-loss updates.
6. Validate actual market/order mapping on the first live trade before declaring the deployment fully accepted.

The worker logs diagnostics to stdout and also keeps a **local** SQLite database at `$SCANNER_DATA_DIR/scanner.db`. By default the directory is `data/`. The database stores worker status, cycle summaries and deduplicated shadow scans, and can reconcile paper results. If local storage is unavailable, it degrades to log-only mode without interrupting API scanning, live execution or stop-loss monitoring.

### Streamlit dashboard limitation

`streamlit_app.py` remains functional for manual scans and diagnostics. Its Worker dashboard can read SQLite using `SCANNER_DB_PATH` when launched on the **same filesystem** as the Railway worker database. A separately hosted Streamlit Cloud instance **cannot** access the Railway Volume. Use Railway logs for remote health checks unless you intentionally colocate the dashboard with the worker. No external database, secret, HTTP dashboard endpoint, or remote storage bridge has been introduced.

### Safeguards and verification

- Live order creation is guarded by the existing Polymarket US executor; no new order paths were added.
- Existing 15%/25% exposure limits, 35¢ stop trigger, and 15-second scan cadence are preserved.
- No Supabase dependency, configuration, schema, or network requests remain in production code.
- Local diagnostics are not a substitute for exchange-side order reconciliation or a permanent execution ledger.
- Tests: `python -m pytest -q` and `python -m compileall -q .`.
- The included `.env.example` lists optional storage settings and required variables; do not commit secrets.

This archive has not been deployed to Railway or tested with authenticated live-money orders. Deploy it yourself to the existing scanner service after retaining a working rollback.
