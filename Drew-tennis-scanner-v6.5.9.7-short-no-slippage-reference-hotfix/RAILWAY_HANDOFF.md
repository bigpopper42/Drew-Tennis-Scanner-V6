# Railway Handoff — Version 6.5.9.7

- Restores the live-required `cashOrderQty` field for market orders.
- Does not submit `quantity` on a cash-sized market order.
- Keeps explicit LONG/YES and SHORT/NO direction fields.
- Keeps up to three ticks of slippage protection using the backed outcome price, clamped at the 99¢ ceiling.
- Keeps exact 20% USD sizing, limited by buying power.
- Keeps event-first moneyline validation and same-market duplicate protection.
- Keeps uncertain submission outcomes `PENDING` rather than blindly resubmitting.
- Keeps fills, partial fills, rejected, pending, expired, and unfilled outcomes separate.
- Corrects telemetry so preview failures retain the real price and sizing details.
- The future 40¢ backed-outcome emergency exit remains inactive.

Deploy the flat-root repository to the existing Railway service. No database migration is required. Preserve the previous deployment commit as the rollback point.
