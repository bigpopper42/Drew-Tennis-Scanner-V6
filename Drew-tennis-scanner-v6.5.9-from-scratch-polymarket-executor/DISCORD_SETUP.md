# Discord Trade Notification Setup — Version 6.5.9

Discord notifications do not change the decision tree. When Polymarket
execution is separately enabled in Railway, Discord reports whether each order
was fill-confirmed, pending verification, rejected, unfilled, or failed.

## 1. Create the Discord channel

1. Open the Discord desktop app or Discord in a browser.
2. Open the server where you want the alerts.
3. Create a text channel such as `tennis-trade-alerts`, or use an existing private channel.

## 2. Create the webhook

1. Open the server name menu.
2. Choose **Server Settings**.
3. Open **Integrations**.
4. Open **Webhooks**.
5. Choose **New Webhook** or **Create Webhook**.
6. Name it `Drew Tennis Scanner`.
7. Select the channel that should receive alerts.
8. Choose **Copy Webhook URL**.

Use the copied URL exactly as Discord provides it. Do not add `/github` or change any part of it.

Treat the webhook URL like a password. Anyone who has it can post into that Discord channel. Do not put it in GitHub, screenshots, or chat messages.

## 3. Add the Railway variables

Open the existing Railway worker service, then open **Variables** and add:

```text
DISCORD_NOTIFICATIONS=true
DISCORD_WEBHOOK_URL=PASTE_THE_FULL_DISCORD_WEBHOOK_URL_HERE
DISCORD_STARTUP_ALERTS=true
```

Keep every existing API Tennis, Supabase, and scanner variable unchanged.

## 4. Deploy the staged changes

Railway stages variable changes. Review and deploy them so the new variables become available to the running worker.

The GitHub repository also must contain Version 6.5.9 before the deployment.

## 5. Confirm it works

After the worker starts, Discord should receive:

```text
Drew Tennis Scanner connected
Version: 6.5.9
Discord trade notifications are active.
Polymarket execution: OFF
```

Railway logs should include:

```text
discord_startup_alert_sent
```

A real approved trade will produce an `ATP TRADE SIGNAL` message and this log event:

```text
discord_trade_alert_sent
```

## 6. Error behavior

If Discord rejects a trade alert, the scanner continues running. The failed alert remains queued and retries on later scan cycles. Look in Railway logs for:

```text
discord_trade_alert_failed
```

A startup failure is shown as:

```text
discord_startup_alert_failed
```

The most common causes are an incomplete webhook URL, a deleted webhook, or the webhook pointing to a server/channel where it no longer exists.
