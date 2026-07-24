# Version 6.3 Build Notes

This release fixes the diagnostic blind spot in Version 6.0.

- `SAVE_ALL_SCANS` is now read from Railway environment variables.
- When true, every evaluated player is inserted into `shadow_scans`.
- `NO TRADE` rows include the exact blocking rules in `decision_reason` and `warnings`.
- Full decision diagnostics are also embedded in `match_snapshot.decision_diagnostics`.
- Non-trade diagnostic rows use `paper_trade_status = NOT_ENTERED`, so outcome settlement only touches real paper TRADE rows.
- When `SAVE_ALL_SCANS=false`, qualified-trade-only storage remains unchanged.
- Dashboard latest-state columns now expose closing-set, tiebreak, break lead, service percentage, current-set protection, and rejection reasons.

No Supabase schema change is required from the Version 6.0 schema.
