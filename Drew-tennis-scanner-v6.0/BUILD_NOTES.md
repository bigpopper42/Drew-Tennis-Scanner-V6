# Version 6.0 Build Notes

## Final decision engine
- Removed market price from every qualification, scoring, threshold, and sizing branch.
- Implemented the final 61% service floor, one-break confirmation rules, immediate two-break maturity, current-set break-volatility rejection, best-of-five match-closing requirement, missing-data fallback, service weighting, ranking adjustments, straight-set bonus, and final 3%/5%/7% thresholds.
- Removed WAIT as a decision state; every scan is either qualified or not qualified at that instant.

## Polymarket
- Added richer public market enrichment and robust nested price, volume, and liquidity extraction.
- Added conservative player-side Long/YES and Short/NO inference.
- Pricing remains informational only.

## Recording and outcomes
- Railway evaluates both players but persists only qualified trades.
- Qualified rows capture current/full service values, opponent service, break-point creation, current-set breaks suffered, both rankings, best-of format, straight/deciding-set flags, serving-for-match state, market timestamp, volume, and liquidity.
- Added recommendation-change metadata and outcome settlement from completed API Tennis fixtures.
- Added safe Supabase migration columns.

## Validation
- 33 tests pass.
- Full Python compilation passes.
