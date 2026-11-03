# Worker dashboard — local-only SQLite

The Streamlit Worker dashboard reads local `scanner.db` in **read-only** mode when its filesystem can access the scanner worker database.

- On the same host/volume as the worker, add `SCANNER_DB_PATH = "/app/data/scanner.db"` to Streamlit secrets (or use `data/scanner.db` if both run from the same directory).
- The worker writes under `SCANNER_DATA_DIR`, default `data/`.
- A separately hosted Streamlit Cloud app cannot view Railway's private volume. Railway logs are the alternative for checking a remote worker; manual scanning and other Streamlit features remain available.
- No cloud DB, dashboard API credentials, or Supabase access is needed.

The dashboard never controls trading or edits the scanner database.
