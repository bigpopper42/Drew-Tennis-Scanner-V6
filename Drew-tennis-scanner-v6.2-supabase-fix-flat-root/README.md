# Drew Tennis Scanner Version 6.2

Version 6.2 is the diagnostic-safe implementation of Drew's late-match stability strategy. It evaluates ATP Tour and Challenger singles continuously, creates 3%, 5%, or 7% paper recommendations from live tennis evidence, and treats Polymarket pricing as informational only.

## Locked V6.2 behavior

- Polymarket price does not participate in qualification, Stability Score, or position sizing.
- `SAVE_ALL_SCANS=true` stores both `TRADE` and `NO TRADE` evaluations with exact blockers. With `false`, only qualified `TRADE` rows are stored.
- Unchanged scans do not create duplicate trade records. Recommendation upgrades create a new qualified record and are alert-eligible.
- Position bands are 75-84.99 = 3%, 85-92.99 = 5%, and 93-100 = 7%.
- Minimum effective service points won is 61%.
- Deciding-set service weighting is 65% current set and 35% full match. Other closing sets use 30% current set and 70% full match.
- Straight-set closing receives a 3-point bonus.
- Major ranking advantage receives +3; major disadvantage receives -2.
- Missing service data can qualify only with a two-break lead and the locked major-ranking-disparity fallback; sizing is capped at 3%.
- ATP best-of-five matches are evaluated only when the backed player is one set from victory.
- Current-set breaks suffered of two or more are a hard rejection. Breaks from earlier sets are not used for that rejection.
- Form, surface form, market price, comfortable holds, and medical-timeout speculation do not drive the recommendation.

## Polymarket information

The matched market is enriched with public market metadata and live BBO data. The app records and displays player-side price, timestamp, volume, and liquidity when available. A missing price never blocks a tennis recommendation.

## Stored scan records

Each stored row includes the complete mapped live state, service metrics, current-set metrics, break information, rankings, match format, Stability Score, recommendation size, informational Polymarket fields, and paper outcome fields. The worker periodically resolves open records from completed API Tennis fixtures and stores `WIN` or `LOSS`, winner, resolution time, and paper P&L when an entry price exists.

## Deployment

1. Run `sql/supabase_schema.sql` in Supabase. It includes safe `ADD COLUMN IF NOT EXISTS` migration statements for an existing V5.6 database.
2. Deploy the repository to Railway using `worker.py`.
3. Keep the existing API Tennis and Supabase environment variables. `SAVE_ALL_SCANS=true` stores every player evaluation, including exact rejection reasons and live-state diagnostics. With `false`, only qualified trades are stored.
4. Deploy `streamlit_app.py` for the dashboard.

## Validation

Run:

```bash
python -m pytest -q
python -m compileall -q .
```

No real orders are placed. Version 6.2 remains a paper/shadow scanner.
