# Deploy Version 6.4 Discord Notifications

This archive is flat-rooted. The GitHub repository homepage must show `worker.py`, `requirements.txt`, `railway.toml`, `scanner/`, and `sql/` directly at the top level.

1. Replace the current GitHub repository contents with this archive's contents.
2. Commit and push the files to the same repository already connected to Railway.
3. Create the Discord webhook using `DISCORD_SETUP.md`.
4. Add these Railway variables:

```text
DISCORD_NOTIFICATIONS=true
DISCORD_WEBHOOK_URL=YOUR_FULL_WEBHOOK_URL
DISCORD_STARTUP_ALERTS=true
```

5. Keep all existing Railway variables, including `SAVE_ALL_SCANS=true`.
6. Deploy the staged Railway changes.
7. Confirm Railway logs show `version: 6.4` and `discord_startup_alert_sent`.
8. Confirm the connection message appears in the selected Discord channel.

No Supabase migration is required for Version 6.4.
