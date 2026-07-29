from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .execution import ExecutionResult

DEFAULT_TIMEOUT = (5.0, 15.0)


class DiscordNotificationError(RuntimeError):
    """Raised when a Discord webhook cannot accept a notification."""


class DiscordNotifier:
    """Send plain-text trade alerts through a private Discord webhook."""

    def __init__(
        self,
        webhook_url: str,
        *,
        timezone_name: str = "America/Phoenix",
        timeout: tuple[float, float] = DEFAULT_TIMEOUT,
    ) -> None:
        self.webhook_url = str(webhook_url or "").strip()
        self.timezone_name = str(timezone_name or "America/Phoenix").strip()
        self.timeout = timeout
        if not self.webhook_url:
            raise ValueError("DISCORD_WEBHOOK_URL is missing.")
        if not self.webhook_url.startswith(
            (
                "https://discord.com/api/webhooks/",
                "https://canary.discord.com/api/webhooks/",
                "https://ptb.discord.com/api/webhooks/",
            )
        ):
            raise ValueError("DISCORD_WEBHOOK_URL must be a Discord webhook URL.")
        self.session = self._build_session()

    @staticmethod
    def _build_session() -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=3,
            connect=3,
            read=3,
            status=3,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"POST"}),
            raise_on_status=False,
        )
        session.mount(
            "https://",
            HTTPAdapter(max_retries=retry, pool_connections=2, pool_maxsize=4),
        )
        session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "DrewTennisScanner/6.5.9-Railway",
            }
        )
        return session

    def send_startup_message(
        self, *, version: str, worker_id: str, execution_enabled: bool = False
    ) -> None:
        content = (
            "✅ **Drew Tennis Scanner connected**\n"
            f"Version: {version}\n"
            f"Worker: {worker_id}\n"
            "Discord trade notifications are active.\n"
            f"Polymarket execution: {'LIVE' if execution_enabled else 'OFF'}"
        )
        self._post(content)

    def send_trade_alert(self, record: Mapping[str, Any]) -> None:
        self._post(self.format_trade_alert(record))

    def send_execution_update(self, result: ExecutionResult) -> None:
        if result.status == "EXECUTED":
            heading = "✅ **POLYMARKET ORDER FILL CONFIRMED**"
        elif result.status == "PENDING":
            heading = "⏳ **POLYMARKET ORDER STATUS UNCONFIRMED**"
        elif result.status == "UNFILLED":
            heading = "🛑 **POLYMARKET ORDER NOT FILLED**"
        elif result.status == "REJECTED":
            heading = "🛑 **POLYMARKET ORDER REJECTED**"
        else:
            heading = "⚠️ **POLYMARKET EXECUTION ERROR**"
        details = [
            heading,
            f"🎾 **{result.player} vs {result.opponent}**",
            f"Status: **{result.status}**",
            f"Reason: {result.reason}",
        ]
        if result.market_slug:
            details.append(f"Market: `{result.market_slug}` · {result.market_side}")
        if result.market_question:
            details.append(f"Contract: **{result.market_question}**")
        if result.market_type:
            details.append(f"Market type: `{result.market_type}`")
        if result.stake_amount:
            details.append(
                f"Stake: **${result.stake_amount:.2f}** · "
                f"Price: **{result.player_price_cents:.1f}¢**"
            )
            details.append(
                f"Sizing: {result.bankroll_pct:g}% of "
                f"${result.account_balance:.2f} account balance"
            )
        if result.recommendation_change:
            details.append(f"Signal: **{result.recommendation_change}**")
        if result.filled_quantity:
            details.append(f"Filled contracts: **{result.filled_quantity:g}**")
        if result.order_state:
            details.append(f"Order state: `{result.order_state}`")
        if result.order_id:
            details.append(f"Order ID: `{result.order_id}`")
        self._post("\n".join(details))

    def _post(self, content: str) -> None:
        payload = {
            "content": str(content)[:2000],
            "allowed_mentions": {"parse": []},
        }
        try:
            response = self.session.post(
                self.webhook_url,
                json=payload,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise DiscordNotificationError(f"Discord webhook request failed: {exc}") from exc
        if response.status_code not in {200, 204}:
            preview = (response.text or "")[:1000].replace("\n", " ")
            raise DiscordNotificationError(
                f"Discord webhook failed with HTTP {response.status_code}: {preview}"
            )

    def format_trade_alert(self, record: Mapping[str, Any]) -> str:
        player = str(record.get("player") or "Unknown player")
        opponent = str(record.get("opponent") or "Unknown opponent")
        tournament = str(record.get("tournament") or "Unknown tournament")
        league = str(record.get("league") or "ATP")
        stability = self._number(record.get("stability_score"), 2)
        break_lead = self._integer(record.get("break_lead"))
        serving = self._yes_no(record.get("serving"))
        serving_for_match = self._yes_no(record.get("serving_for_match"))
        service_pct = self._percent(record.get("effective_service_points_won_pct"))
        current_set = self._current_set_score(record)
        current_game = str(record.get("current_game_score") or "Unknown")
        market = self._market_line(record)
        time_label = self._time_label(record.get("scanned_at"))

        return (
            "🚨 **ATP TRADE SIGNAL**\n\n"
            f"🎾 **{player} vs {opponent}**\n"
            f"🎯 Trade: **{player}**\n"
            f"🏆 {league} · {tournament}\n"
            f"📍 Current set: {current_set} · Game: {current_game}\n"
            f"📈 Stability: **{stability}**\n"
            f"✅ Break lead: {break_lead} · Serving: {serving}\n"
            f"🏁 Serving for match: {serving_for_match}\n"
            f"💪 Service points won: {service_pct}\n"
            "💰 Live order size: **20% of authenticated balance**\n"
            f"🔎 {market}\n"
            f"🕒 {time_label}"
        )

    @staticmethod
    def _number(value: Any, decimals: int) -> str:
        try:
            return f"{float(value):.{decimals}f}"
        except (TypeError, ValueError):
            return "Unknown"

    @staticmethod
    def _integer(value: Any) -> str:
        try:
            return str(int(float(value)))
        except (TypeError, ValueError):
            return "Unknown"

    @staticmethod
    def _money(value: Any) -> str:
        try:
            return f"${float(value):,.2f}"
        except (TypeError, ValueError):
            return "$0.00"

    @staticmethod
    def _percent(value: Any) -> str:
        try:
            return f"{float(value):.1f}%"
        except (TypeError, ValueError):
            return "Unknown"

    @staticmethod
    def _yes_no(value: Any) -> str:
        if value is True:
            return "Yes"
        if value is False:
            return "No"
        return "Unknown"

    @classmethod
    def _current_set_score(cls, record: Mapping[str, Any]) -> str:
        player_games = record.get("backed_player_games_in_set")
        opponent_games = record.get("opponent_games_in_set")
        try:
            return f"{int(float(player_games))}-{int(float(opponent_games))}"
        except (TypeError, ValueError):
            return "Unknown"

    @staticmethod
    def _market_line(record: Mapping[str, Any]) -> str:
        if not record.get("market_found"):
            if record.get("execution_market_lookup_retry_enabled"):
                return (
                    "Public lookup unavailable · live executor will resolve "
                    "the exact event and moneyline"
                )
            return "Polymarket market not matched"
        try:
            price = float(record.get("market_price_cents") or 0.0)
        except (TypeError, ValueError):
            price = 0.0
        title = str(record.get("market_title") or "").strip()
        market_type = str(
            record.get("sports_market_type_v2")
            or record.get("market_type")
            or ""
        ).strip()
        provisional = bool(record.get("market_discovery_candidate")) and not bool(
            record.get("market_public_moneyline_confirmed")
        )
        pieces = [
            "Polymarket candidate found · authenticated validation pending"
            if provisional
            else "Polymarket market matched"
        ]
        if title:
            pieces.append(f"Contract: {title}")
        if market_type:
            pieces.append(f"Type: {market_type}")
        if price > 0:
            pieces.append(f"{price:.1f}¢")
        return " · ".join(pieces)

    def _time_label(self, scanned_at: Any) -> str:
        raw = str(scanned_at or "").strip()
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            try:
                zone = ZoneInfo(self.timezone_name)
            except ZoneInfoNotFoundError:
                zone = timezone.utc
            return parsed.astimezone(zone).strftime("%b %-d, %Y at %-I:%M:%S %p %Z")
        except (TypeError, ValueError):
            return raw or "Unknown time"
