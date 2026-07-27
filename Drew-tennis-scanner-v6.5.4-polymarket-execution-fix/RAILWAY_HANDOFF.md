# Railway Handoff — Version 6.5.4

Version 6.5.4 adds guarded Polymarket US execution without changing the scanner's
decision tree. See `POLYMARKET_EXECUTION_SETUP.md` before enabling it.

Required new service variables:

```text
DISCORD_NOTIFICATIONS=true
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
DISCORD_STARTUP_ALERTS=true
POLYMARKET_EXECUTION_ENABLED=false
```

Expected startup log events:

```text
worker_ready
version: 6.5
discord_startup_alert_sent
```

Expected approved-trade log event:

```text
discord_trade_alert_sent
```

If a trade notification temporarily fails, it remains queued and retries on later cycles. The scanner continues operating.

Live execution requires the Polymarket key variables plus
`POLYMARKET_EXECUTION_ENABLED=true`. Execution attempts are never retried
automatically after an API submission attempt.
