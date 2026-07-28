# Polymarket US Live Execution Setup

Version 6.5.8 sends each new approved scanner signal to Discord and the guarded Polymarket US execution engine. The scanner remains the only tennis decision maker.

## Locked live behavior

- Stake: 20% of authenticated account `currentBalance`, rounded down to cents.
- Buying-power limit: the order never exceeds available buying power.
- Fixed dollar cap: none in scanner code.
- Concurrent exposure: unlimited distinct markets may be open at the same time.
- Same-market upgrades: a scanner-approved `UPGRADE` may add to an existing position.
- Duplicate protection: unchanged signals and unfinished same-market orders remain blocked.
- Market type: only the ordinary match-winner moneyline is allowed.
- Lookup fallback: rejected props do not stop surname, league, or tennis-wide searches for the real moneyline.
- Ranked validation: execution checks candidate slugs through the SDK in order and skips invalid props or name mismatches instead of stopping at the first result.
- Generic market support: when type text is omitted, exactly two different named players on opposite LONG/SHORT contracts can validate the moneyline after all prop signatures are excluded.
- Market order: immediate-or-cancel with configured slippage tolerance.
- Regulatory flag: `MANUAL_ORDER_INDICATOR_AUTOMATIC`.
- Preview: the exact request is previewed before submission.
- Verification: the order ID is queried through the authenticated order-status endpoint before Discord reports a confirmed fill.

## Exact-score protection

The bot rejects:

- `SPORTS_MARKET_TYPE_PROP`
- `SPORTS_MARKET_TYPE_SPREAD`
- `SPORTS_MARKET_TYPE_TOTAL`
- exact-score or correct-score markets
- `wins 2-0`, `2-0`, `wins 2 sets to 0`, and similar contracts
- slugs containing exact-score patterns such as `-es-0-2`
- set-winner, game-winner, tiebreak, handicap, and total markets

The authenticated contract question and market type are shown in the Discord execution message.

## Other rejection safeguards

No order is sent when:

- the scanner has not safely matched a market;
- match confidence is below the execution minimum;
- the authenticated market is not a match-winner moneyline;
- both players cannot be mapped safely to opposite authenticated market sides;
- the market or order book is inactive, closed, suspended, or otherwise not open;
- the same exact market still has an unfinished open order;
- a same-market position exists and the signal is not an `UPGRADE`;
- the backed-player price is outside the configured range;
- 20% is below the minimum order;
- the account lacks buying power;
- preview or submission fails.

## Railway variables

Keep the existing credentials and execution settings:

```text
POLYMARKET_KEY_ID=YOUR_KEY_ID
POLYMARKET_SECRET_KEY=YOUR_SECRET_KEY
POLYMARKET_EXECUTION_ENABLED=true

EXECUTION_MIN_ORDER_USD=0.50
EXECUTION_MIN_PRICE_CENTS=50
EXECUTION_MAX_PRICE_CENTS=99
EXECUTION_SLIPPAGE_TICKS=1
EXECUTION_MIN_MARKET_CONFIDENCE=80
```

Legacy `EXECUTION_BANKROLL_PCT` and `EXECUTION_MAX_ORDER_USD` variables may remain in Railway. Version 6.5.8 ignores them.

## Discord execution meanings

- `EXECUTED`: a fill or partial fill was confirmed.
- `PENDING`: an order ID exists, but final status could not yet be confirmed. This is not labeled as placed or filled.
- `REJECTED`: Polymarket rejected the order.
- `UNFILLED`: the IOC order canceled or expired without a fill.
- `FAILED`: preview, submission, authentication, transport, or response validation failed.

## Emergency stop

Set this Railway variable to false and redeploy:

```text
POLYMARKET_EXECUTION_ENABLED=false
```

The scanner and Discord alerts continue, but no orders are attempted.
