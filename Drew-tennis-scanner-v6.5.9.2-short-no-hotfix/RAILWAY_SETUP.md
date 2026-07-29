# Railway Worker Setup — Version 6.5.9.2

This worker scans live tennis, stores shadow diagnostics, sends Discord alerts,
and can place guarded Polymarket US orders when live execution is explicitly
enabled. Follow `POLYMARKET_EXECUTION_SETUP.md` for the trading variables.

## 1. Create the Supabase database

1. Create a Supabase project.
2. Open **SQL Editor**.
3. Create a new query.
4. Paste the entire contents of `sql/supabase_schema.sql`.
5. Press **Run**.
6. Confirm these tables exist in **Table Editor**:
   - `worker_status`
   - `scan_cycles`
   - `shadow_scans`

## 2. Copy the Supabase server credentials

From the Supabase project dashboard, copy:

- Project URL → `SUPABASE_URL`
- A server-side **Secret key** → `SUPABASE_SECRET_KEY`

The newer `sb_secret_...` key is preferred. A legacy `service_role` key also works through `SUPABASE_SERVICE_ROLE_KEY`.

Never put either server-side key in Streamlit, browser code, GitHub, screenshots, or chat messages.

## 3. Push this repository to GitHub

The repository root must include:

```text
worker.py
railway.toml
requirements.txt
scanner/
sql/
streamlit_app.py
```

The same repository can continue powering Streamlit. Railway runs `worker.py`; Streamlit Cloud continues running `streamlit_app.py`.

## 4. Create the Railway worker

1. Open Railway and create a new project.
2. Choose **Deploy from GitHub repo**.
3. Select the tennis scanner repository.
4. Name the service `tennis-shadow-worker`.
5. Do not add a public domain.
6. Do not configure a cron schedule. This is an always-on background worker.

`railway.toml` supplies:

```text
Start command: python worker.py
Restart policy: On Failure
```

## 5. Add Railway variables

Open the service's **Variables** tab and paste:

```text
API_TENNIS_KEY=YOUR_API_TENNIS_KEY
SUPABASE_URL=https://YOUR_PROJECT_REF.supabase.co
SUPABASE_SECRET_KEY=YOUR_SB_SECRET_KEY
TIMEZONE=America/Phoenix
SCAN_INTERVAL_SECONDS=30
SHADOW_BANKROLL=100
DRY_RUN=false
SAVE_ALL_SCANS=true
FIXTURES_FALLBACK_INTERVAL_SECONDS=300
RANKINGS_REFRESH_SECONDS=21600
MARKET_CACHE_TTL_SECONDS=1800
UNMATCHED_RETRY_SECONDS=300
MARKET_SEARCH_PAGES=2
MIN_MARKET_CONFIDENCE=80
MAX_EVENTS_PER_CYCLE=0
MAX_PENDING_RECORDS=5000
DISCORD_NOTIFICATIONS=true
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/REPLACE_ME
DISCORD_STARTUP_ALERTS=true
POLYMARKET_EXECUTION_ENABLED=false
```

Use `SUPABASE_SERVICE_ROLE_KEY` instead of `SUPABASE_SECRET_KEY` only when your project still uses the legacy key.

## 5A. Create the Discord webhook

Follow `DISCORD_SETUP.md`. Keep the full webhook URL private and paste it only into Railway's `DISCORD_WEBHOOK_URL` service variable.

## 6. Deploy and inspect logs

A healthy startup produces JSON log lines containing:

```text
worker_ready
discord_startup_alert_sent
cycle_complete
```

For the first diagnostic deployment, keep `SAVE_ALL_SCANS=true`. After the rejection reasons have been verified, it can be changed to `false` to store only qualified trades.

A completed cycle reports counts for:

- API Tennis events
- supported singles
- matched and unmatched Polymarket markets
- player scans
- trade signals
- inserted and duplicate database rows

`DEGRADED` means the worker stayed alive but one or more events, market lookups, or database writes had warnings. `FAILED` means the cycle could not complete.

## 7. Verify Supabase

Run these in Supabase SQL Editor:

```sql
select *
from public.worker_status
order by last_seen_at desc;
```

```sql
select started_at, status, api_events, supported_events,
       markets_matched, markets_unmatched, player_scans,
       trade_signals, inserted_scans, duplicate_scans
from public.scan_cycles
order by started_at desc
limit 20;
```

```sql
select scanned_at, player, opponent, tournament,
       market_found, market_price_cents,
       decision_status, stability_score,
       data_completeness_pct
from public.shadow_scans
order by scanned_at desc
limit 50;
```

## Important operating rules

- Keep exactly one Railway replica during initial validation.
- Keep `DRY_RUN=false` only after the Supabase schema is installed.
- Put Polymarket credentials only in Railway Variables, never GitHub.
- Keep `POLYMARKET_EXECUTION_ENABLED=false` until all variables in
  `POLYMARKET_EXECUTION_SETUP.md` are installed and reviewed.
- Do not use Railway Cron. Railway cron cannot run every 30 seconds and is not intended for continuous live scanning.
- The worker caches market matches, refreshes rankings slowly, retries unmatched markets, and deduplicates unchanged match states before writing to Supabase.


## 8. Connect the Streamlit dashboard

The Railway variables stay unchanged. To see the worker inside Streamlit, follow `STREAMLIT_DASHBOARD_SETUP.md`.
