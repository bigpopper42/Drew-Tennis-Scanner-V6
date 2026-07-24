# Railway Handoff — Version 6.0

The existing Railway worker remains the always-on scanner.

```text
worker.py
    -> scanner.worker_runtime.RailwayShadowWorker
    -> API Tennis live snapshot
    -> API event pipeline
    -> cached Polymarket matching
    -> BBO price inference
    -> both-player decision engine
    -> Supabase shadow storage
    -> Streamlit Worker dashboard
```

Railway start command:

```text
python worker.py
```

Required Railway variables:

```text
API_TENNIS_KEY
SUPABASE_URL
SUPABASE_SECRET_KEY
```

The legacy `SUPABASE_SERVICE_ROLE_KEY` remains supported as an alternative.

Railway does not need a public domain. Streamlit reads the results from Supabase, not directly from Railway.

See `RAILWAY_SETUP.md` for deployment and `STREAMLIT_DASHBOARD_SETUP.md` for the dashboard connection.
