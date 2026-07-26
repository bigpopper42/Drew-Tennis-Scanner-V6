from __future__ import annotations

from typing import Any, Mapping

import pytest

from scanner.discord_notifier import DiscordNotificationError, DiscordNotifier
from scanner.worker_runtime import CycleReport, RailwayShadowWorker, WorkerConfig


class FakeResponse:
    def __init__(self, status_code: int = 204, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, responses: list[FakeResponse] | None = None) -> None:
        self.responses = list(responses or [FakeResponse()])
        self.calls: list[dict[str, Any]] = []

    def post(self, url: str, *, json: dict[str, Any], timeout: Any) -> FakeResponse:
        self.calls.append({"url": url, "json": json, "timeout": timeout})
        return self.responses.pop(0) if self.responses else FakeResponse()


class FakeNotifier:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.fail_first = fail_first
        self.calls: list[Mapping[str, Any]] = []

    def send_trade_alert(self, record: Mapping[str, Any]) -> None:
        self.calls.append(record)
        if self.fail_first:
            self.fail_first = False
            raise DiscordNotificationError("temporary failure")


def sample_record(*, stake_pct: float = 5.0, eligible: bool = True) -> dict[str, Any]:
    return {
        "decision_status": "TRADE",
        "alert_eligible": eligible,
        "trade_key": "123|a. michelsen",
        "player": "A. Michelsen",
        "opponent": "M. Lajal",
        "tournament": "Bloomfield Hills",
        "league": "ATP",
        "stability_score": 86.86,
        "stake_pct": stake_pct,
        "stake_amount": 5.0,
        "bankroll": 100.0,
        "break_lead": 1,
        "serving": True,
        "serving_for_match": True,
        "effective_service_points_won_pct": 82.0,
        "backed_player_games_in_set": 5,
        "opponent_games_in_set": 4,
        "current_game_score": "30-0",
        "market_found": True,
        "market_price_cents": 98.0,
        "scanned_at": "2026-07-24T19:30:00-07:00",
    }


def make_worker() -> RailwayShadowWorker:
    config = WorkerConfig(
        api_tennis_key="test-key",
        supabase_url="",
        supabase_key="",
        dry_run=True,
        discord_notifications=False,
        worker_id="test-worker",
    )
    return RailwayShadowWorker(config)


def test_discord_formats_basic_trade_alert() -> None:
    notifier = DiscordNotifier(
        "https://discord.com/api/webhooks/123/token",
        timezone_name="America/Phoenix",
    )
    message = notifier.format_trade_alert(sample_record())

    assert "ATP TRADE SIGNAL" in message
    assert "A. Michelsen vs M. Lajal" in message
    assert "Current set: 5-4" in message
    assert "Game: 30-0" in message
    assert "Stability: **86.86**" in message
    assert "Scanner tier: **5%** ($5.00 of $100.00)" in message
    assert "98.0¢" in message


def test_discord_post_uses_safe_plain_text_payload() -> None:
    notifier = DiscordNotifier("https://discord.com/api/webhooks/123/token")
    session = FakeSession()
    notifier.session = session

    notifier.send_trade_alert(sample_record())

    assert len(session.calls) == 1
    payload = session.calls[0]["json"]
    assert payload["allowed_mentions"] == {"parse": []}
    assert len(payload["content"]) <= 2000


def test_discord_http_error_is_reported() -> None:
    notifier = DiscordNotifier("https://discord.com/api/webhooks/123/token")
    notifier.session = FakeSession([FakeResponse(404, "Unknown Webhook")])

    with pytest.raises(DiscordNotificationError, match="HTTP 404"):
        notifier.send_trade_alert(sample_record())


def test_worker_sends_each_trade_tier_once() -> None:
    worker = make_worker()
    fake = FakeNotifier()
    worker.discord_notifier = fake
    report = CycleReport(cycle_id="cycle", started_at="2026-07-24T00:00:00+00:00")

    record = sample_record(stake_pct=5.0)
    worker._queue_discord_alerts([record, record])
    worker._flush_discord_alerts(report)
    worker._queue_discord_alerts([record])
    worker._flush_discord_alerts(report)

    assert len(fake.calls) == 1

    upgraded = sample_record(stake_pct=7.0)
    worker._queue_discord_alerts([upgraded])
    worker._flush_discord_alerts(report)
    assert len(fake.calls) == 2


def test_failed_discord_alert_stays_queued_and_retries() -> None:
    worker = make_worker()
    fake = FakeNotifier(fail_first=True)
    worker.discord_notifier = fake
    report = CycleReport(cycle_id="cycle", started_at="2026-07-24T00:00:00+00:00")

    worker._queue_discord_alerts([sample_record()])
    worker._flush_discord_alerts(report)
    assert len(worker.pending_discord_alerts) == 1
    assert report.warnings

    worker._flush_discord_alerts(report)
    assert len(worker.pending_discord_alerts) == 0
    assert len(fake.calls) == 2


def test_non_trade_or_ineligible_record_is_not_queued() -> None:
    worker = make_worker()
    worker.discord_notifier = FakeNotifier()
    no_trade = sample_record()
    no_trade["decision_status"] = "NO TRADE"

    worker._queue_discord_alerts([no_trade, sample_record(eligible=False)])

    assert worker.pending_discord_alerts == {}
