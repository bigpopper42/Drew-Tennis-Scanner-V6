# Polymarket US Live Execution Setup

Version 6.5 sends each new approved scanner signal to both Discord and the
guarded Polymarket US execution engine. The engine does not make tennis
decisions and does not use the scanner's displayed price.

## Locked live behavior

- Stake: 10% of authenticated account `currentBalance`, rounded down to cents.
- Buying-power cap: the order never exceeds current available buying power.
- Maximum concurrent exposure: one open order or position.
- Market order: immediate-or-cancel with one tick of slippage tolerance.
- Regulatory flag: every submitted order is marked
  `MANUAL_ORDER_INDICATOR_AUTOMATIC`.
- Preview: the exact order is previewed before submission.
- Duplicate protection: one execution attempt per player/match signal while the
  worker process is running.

## Rejection safeguards

No order is sent when:

- the scanner has not safely matched a Polymarket US market;
- the player cannot be mapped safely to the YES or NO side;
- match confidence is below 80;
- the live market names no longer match both players;
- the market is inactive, suspended, halted, or closed;
- another order or position is already open;
- the backed-player price is outside 50¢ through 99¢;
- 10% is below $0.50 or above the configured $25 order cap;
- the account does not have enough buying power;
- the order preview fails.

## Railway variables

Add these variables to the existing Railway service. Use the Key ID and Secret
Key from the Polymarket US developer portal. Never put either key in GitHub,
Discord, screenshots, or this file.

```text
POLYMARKET_KEY_ID=YOUR_KEY_ID
POLYMARKET_SECRET_KEY=YOUR_SECRET_KEY
POLYMARKET_EXECUTION_ENABLED=true

EXECUTION_BANKROLL_PCT=10
EXECUTION_MIN_ORDER_USD=0.50
EXECUTION_MAX_ORDER_USD=25
EXECUTION_MIN_PRICE_CENTS=50
EXECUTION_MAX_PRICE_CENTS=99
EXECUTION_SLIPPAGE_TICKS=1
EXECUTION_MIN_MARKET_CONFIDENCE=80
```

Keep the existing API Tennis, Supabase, and Discord variables unchanged. After
Railway redeploys, Discord's startup message must show:

```text
Polymarket execution: LIVE
```

Each signal will then receive a second Discord message saying the order was
placed, blocked by a safeguard, or failed.

The first Discord message continues to show the scanner's 3%, 5%, or 7% scoring
tier. The second execution message shows the actual live stake, which is fixed
at 10% of the authenticated account balance.

Version 6.5 automates entry and holds filled contracts for normal market
resolution. It does not automatically sell a filled position early.

## Emergency stop

Change this Railway variable and redeploy:

```text
POLYMARKET_EXECUTION_ENABLED=false
```

The scanner and Discord alerts continue running, but no orders are attempted.
