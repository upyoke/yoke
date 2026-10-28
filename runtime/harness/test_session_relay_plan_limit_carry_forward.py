"""An unreadable refresh keeps the last read windows until they reset."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_contracts.session_control.plan_limits import (
    plan_limit_window,
    surface_reading,
    unknown_reading,
)
from yoke_harness import session_relay_plan_limits as limits

FIRST = "2026-10-28T00:00:00.000000Z"
LATER = "2026-10-28T02:00:00.000000Z"
AFTER_SESSION_RESET = "2026-10-28T04:00:00.000000Z"
SESSION_RESET = "2026-10-28T03:00:00.000000Z"
WEEKLY_RESET = "2026-11-01T00:00:00.000000Z"


def _window(kind: str, remaining: float, resets_at: str) -> dict:
    return plan_limit_window(
        window_kind=kind,
        scope="all",
        meter=kind,
        remaining_percent=remaining,
        resets_at=resets_at,
    )


def _ok_reading(surface: str, observed_at: str) -> dict:
    return surface_reading(
        surface,
        observed_at=observed_at,
        plan_tier="max",
        windows=(
            _window("rolling_5h", 60.0, SESSION_RESET),
            _window("rolling_7d", 40.0, WEEKLY_RESET),
        ),
    )


def _observe(monkeypatch, tmp_path: Path, at: str, reading) -> dict:
    monkeypatch.setattr(limits, "_probe_one", lambda surface, observed_at: reading)
    return limits.observe_plan_limits(
        ("claude-cli",), state_dir=tmp_path, now=at, clock=lambda: at
    )["claude-cli"]


def _windows(reading: dict) -> list[tuple]:
    return [
        (w["window_kind"], w["status"], w["remaining_percent"], w["reason"])
        for w in reading["windows"]
    ]


def _read_then_fail(monkeypatch, tmp_path: Path, at: str, reason: str) -> dict:
    _observe(monkeypatch, tmp_path, FIRST, _ok_reading("claude-cli", FIRST))
    failed = unknown_reading("claude-cli", reason, observed_at=at)
    return _observe(monkeypatch, tmp_path, at, failed)


@pytest.mark.parametrize("reason", ["credential_expired", "http_429", "http_500"])
def test_running_windows_are_kept_with_their_original_observation(
    monkeypatch, tmp_path, reason
):
    reading = _read_then_fail(monkeypatch, tmp_path, LATER, reason)
    assert reading["observed_at"] == FIRST
    assert _windows(reading) == [
        ("rolling_5h", "ok", 60.0, None),
        ("rolling_7d", "ok", 40.0, None),
    ]


def test_a_window_past_its_reset_is_dropped(monkeypatch, tmp_path):
    reading = _read_then_fail(
        monkeypatch, tmp_path, AFTER_SESSION_RESET, "credential_expired"
    )
    assert _windows(reading) == [("rolling_7d", "ok", 40.0, None)]


def test_no_running_window_left_reports_the_new_reason(monkeypatch, tmp_path):
    past_weekly = "2026-11-02T00:00:00.000000Z"
    reading = _read_then_fail(monkeypatch, tmp_path, past_weekly, "credential_expired")
    assert reading["observed_at"] == past_weekly
    assert _windows(reading) == [("unknown", "unknown", None, "credential_expired")]


@pytest.mark.parametrize("reason", ["stale_credential", "codex_auth_401"])
def test_a_rejected_sign_in_is_not_carried(monkeypatch, tmp_path, reason):
    reading = _read_then_fail(monkeypatch, tmp_path, LATER, reason)
    assert _windows(reading) == [("unknown", "unknown", None, reason)]


def test_carried_windows_survive_a_cache_round_trip(monkeypatch, tmp_path):
    _read_then_fail(monkeypatch, tmp_path, LATER, "credential_expired")
    cached = json.loads(limits._cache_path(tmp_path).read_text())
    assert cached["surfaces"]["claude-cli"]["observed_at"] == FIRST


@pytest.fixture
def claude_credentials(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(limits.sys, "platform", "linux")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    def write(expires_at):
        oauth = {"accessToken": "fixture-token", "expiresAt": expires_at}
        (tmp_path / ".claude").mkdir(exist_ok=True)
        (tmp_path / ".claude" / ".credentials.json").write_text(
            json.dumps({"claudeAiOauth": oauth})
        )

    return write


def _epoch_ms(instant: str) -> int:
    from yoke_contracts.timestamps import parse_instant

    return int(parse_instant(instant).timestamp() * 1000)


def test_expired_token_sends_no_request(monkeypatch, claude_credentials):
    claude_credentials(_epoch_ms(FIRST) - 1)

    def forbidden(*args, **kwargs):
        pytest.fail("an expired token must not reach the CLI or the vendor")

    monkeypatch.setattr(limits, "probe_cli_surface", forbidden)
    monkeypatch.setattr(limits, "plan_limit_http_json", forbidden)
    reading = limits.probe_claude_cli(observed_at=FIRST)
    assert _windows(reading) == [("unknown", "unknown", None, "credential_expired")]


def test_unexpired_token_reaches_the_usage_check(monkeypatch, claude_credentials):
    claude_credentials(_epoch_ms(FIRST) + 60_000)
    monkeypatch.setattr(
        limits,
        "probe_cli_surface",
        lambda *args: SimpleNamespace(verdict="ok", version="2.3.4", error=None),
    )
    sent = []

    def http(url, **kwargs):
        sent.append(kwargs["headers"]["Authorization"])
        return {"limits": [{"kind": "session", "percent": 25}]}

    monkeypatch.setattr(limits, "plan_limit_http_json", http)
    reading = limits.probe_claude_cli(observed_at=FIRST)
    assert sent == ["Bearer fixture-token"]
    assert reading["windows"][0]["remaining_percent"] == 75
