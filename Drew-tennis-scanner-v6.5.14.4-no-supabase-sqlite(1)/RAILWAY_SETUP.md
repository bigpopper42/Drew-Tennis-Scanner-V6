# Railway worker deployment — v6.5.14.4

Use the **existing** Railway scanner service. Push ZIP contents to the repository root; service command stays `python worker.py`. Set required variables `API_TENNIS_KEY`, `TIMEZONE=America/Phoenix`, the existing Discord and Polymarket US credentials, and your existing trading and notifications flags.

A persistent Railway Volume at `/app/data` with `SCANNER_DATA_DIR=/app/data` preserves `scanner.db` across restarts. Without it, diagnostics are ephemeral; the scanner will continue even when local storage is unavailable. Supabase credentials are no longer necessary and should be removed from Railway.

The pre-deployment safety check `python worker.py --check-config` validates config, local SQLite tables and startup notifications. `python worker.py --once` performs exactly one scan cycle (it may use live trading settings, so use only with appropriate configuration). Do not enable real trading for testing unless you intentionally intend real trades.

Verify logs for `worker_ready`, `cycle_complete`, and authenticated Polymarket execution state; preserve the previous working deployment for rollback.
