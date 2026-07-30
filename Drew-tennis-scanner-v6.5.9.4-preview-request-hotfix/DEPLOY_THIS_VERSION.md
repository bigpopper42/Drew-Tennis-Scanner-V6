# Deploy Version 6.5.9.4

This is a complete flat-root repository replacement. Opening the ZIP should show `worker.py`, `requirements.txt`, `railway.toml`, `scanner/`, `tests/`, and the setup files directly.

1. Preserve the current working Git commit or ZIP as the rollback version.
2. Replace the current GitHub repository contents with this ZIP's contents.
3. Commit and push.
4. Redeploy Railway.
5. Confirm the startup log and Discord connection message report Version `6.5.9.4` and `Polymarket execution: LIVE`.

No Supabase migration and no new Railway environment variable are required.

## Entry-order behavior

Version 6.5.9.4 restores the required preview `request` envelope and uses price-capped IOC limit entries for both LONG/YES and SHORT/NO. A SHORT/NO order still sends the explicit NO outcome fields, while its limit price is correctly expressed using Polymarket's required YES-reference price.

If an IOC order receives no fill, Discord will now say that executable quantity was unavailable at the allowed price instead of incorrectly presenting the default `ORD_REJECT_REASON_EXCHANGE_OPTION` enum as the cause.

## Stop-loss status

The proposed emergency exit trigger is now **40¢ on the backed outcome**, but this stop feature is not active in Version 6.5.9.4.
