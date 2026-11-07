# v6.5.14.5 — Multi-letter tennis name abbreviations

Fixed execution-side tennis name comparison in `scanner/polymarket_executor.py` to support multi-letter given-name prefixes such as `Dar. Blanch` versus `Darwin Blanch`. The previous logic only supported a single initial or an exact multi-letter given name.

Retains strict surname matching, first-letter matching, unique mapping to two distinct market sides, market-type checks, and LONG/SHORT validation. No changes to signals, trade sizing, stop-loss, or trading strategy.

Added two regression cases for `B. Shick` / `Dar. Blanch` and reversed player order.

Validation: 209 automated tests passed. This does not prove that the live authenticated Polymarket API will return identical market metadata, or that all missed matches have this cause. Monitor market-selection errors after deployment.
