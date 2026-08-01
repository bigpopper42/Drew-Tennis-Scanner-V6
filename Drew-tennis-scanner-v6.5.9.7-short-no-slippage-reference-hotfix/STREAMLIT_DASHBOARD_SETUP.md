# Streamlit Worker Dashboard Setup — Version 6.0

The Worker dashboard reads the same private Supabase tables that the Railway worker writes.

## 1. Open Streamlit Secrets

Open the deployed Streamlit app, then:

```text
Manage app -> Settings -> Secrets
```

## 2. Add these values

```toml
API_TENNIS_KEY = "YOUR_API_TENNIS_KEY"
SUPABASE_URL = "https://YOUR_PROJECT_REF.supabase.co"
SUPABASE_SECRET_KEY = "YOUR_SB_SECRET_KEY"
WORKER_OFFLINE_AFTER_SECONDS = 120
```

Important:

- `SUPABASE_URL` must end at `.supabase.co`.
- Do not add `/rest/v1`.
- Use the same server-side Supabase secret already stored in Railway.
- The secret is used only by the Streamlit server and is never requested through the visible app interface.
- Never commit `.streamlit/secrets.toml` to GitHub.

A legacy service-role key can be supplied as:

```toml
SUPABASE_SERVICE_ROLE_KEY = "YOUR_LEGACY_SERVICE_ROLE_KEY"
```

Use only one Supabase key variable.

## 3. Save and reboot the Streamlit app

After saving the secrets, reboot or redeploy the app once.

## 4. Open the dashboard

Choose:

```text
Workspace -> Worker dashboard
```

The page should show:

- Worker online or offline
- Last heartbeat
- Last completed cycle
- API live events
- Supported matches
- Markets matched and unmatched
- Player scans
- Trade signals
- Recent scan history
- Latest match states
- Warnings and errors

## Expected zero state

When no supported matches are live, the worker can still be healthy while all scan counters are zero. The worker is considered online when its heartbeat is fresh, not when it finds a match.

## Security boundary

The dashboard client is read-only and issues GET requests only. It cannot modify Supabase rows, control Railway, access a wallet, or place a Polymarket trade.
