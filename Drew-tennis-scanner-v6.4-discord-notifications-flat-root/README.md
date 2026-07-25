# Drew Tennis Scanner Version 6.4

Version 6.4 keeps Drew's locked late-match decision tree unchanged and adds immediate Discord webhook notifications for approved `TRADE` signals. The worker still evaluates ATP Tour and Challenger singles continuously, creates 3%, 5%, or 7% paper recommendations from live tennis evidence, and treats Polymarket pricing as informational only.

## Locked strategy behavior

- Polymarket price does not participate in qualification, Stability Score, or position sizing.
- `SAVE_ALL_SCANS=true` stores both `TRADE` and `NO TRADE` evaluations with exact blockers. With `false`, only qualified `TRADE` rows are stored.
- Position bands are 75-84.99 = 3%, 85-92.99 = 5%, and 93-100 = 7%.
- Minimum effective service points won is 61%.
- Deciding-set service weighting is 65% current set and 35% full match. Other closing sets use 30% current set and 70% full match.
- Straight-set closing receives a 3-point bonus.
- Major ranking advantage receives +3; major disadvantage receives -2.
- Missing service data can qualify only with a two-break lead and the locked major-ranking-disparity fallback; sizing is capped at 3%.
- ATP best-of-five matches are evaluated only when the backed player is one set from victory.
- Current-set breaks suffered of two or more are a hard rejection. Breaks from earlier sets are not used for that rejection.
- Form, surface form, market price, comfortable holds, and medical-timeout speculation do not drive the recommendation.

## Discord notifications

When `DISCORD_NOTIFICATIONS=true`, the Railway worker sends a plain-text message to the configured webhook whenever a player first becomes a `TRADE`. A higher position-size tier can send one additional upgrade alert. Unchanged qualifying states are not repeatedly sent.

The alert includes:

- player and opponent
- tournament
- current set and current game score
- Stability Score
- break lead and serving state
- effective service-points-won percentage
- recommended position size
- informational Polymarket match and price when available
- Arizona-local timestamp when `TIMEZONE=America/Phoenix`

Failed trade notifications remain queued in memory and retry on later scan cycles without stopping the scanner. The webhook URL is never included in logs or the public worker summary.

See `DISCORD_SETUP.md` for the exact setup steps.

## Stored scan records

Each stored row includes the complete mapped live state, service metrics, current-set metrics, break information, rankings, match format, Stability Score, recommendation size, informational Polymarket fields, and paper outcome fields. The worker periodically resolves open records from completed API Tennis fixtures and stores `WIN` or `LOSS`, winner, resolution time, and paper P&L when an entry price exists.

## Deployment

1. Keep the existing Supabase schema and Railway service.
2. Replace the GitHub repository contents with this archive.
3. Create a Discord webhook and add the three Discord Railway variables listed in `DISCORD_SETUP.md`.
4. Redeploy Railway and confirm the startup message appears in Discord.
5. Keep `SAVE_ALL_SCANS=true` while reviewing rejected decisions.

## Validation

```bash
python -m pytest -q
python -m compileall -q .
```

Validated build result: **44 tests passed**.

No real orders are placed. Version 6.4 remains a paper/shadow scanner with notification-only automation.
