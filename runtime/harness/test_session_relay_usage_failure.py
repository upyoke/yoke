"""Failed usage responses remain visible through cache, guidance and Fleet."""

from datetime import timedelta
from email.message import Message
from yoke_contracts.timestamps import parse_instant
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import urllib.error
import urllib.request

import pytest

from yoke_contracts.session_control.plan_limit_unreadable_guidance import (
    THROTTLED_GUIDANCE,
    unreadable_guidance,
)
from yoke_core.domain.steering_fleet_plan_capacity import plan_limit_lines
from yoke_core.domain.steering_fleet_report_limits import MachinePlanLimit
from yoke_harness import session_relay_codex_plan_limit as codex
from yoke_harness import session_relay_plan_limits as limits


@pytest.mark.parametrize("surface", ["claude-cli", "cursor-cli", "codex-cli"])
@pytest.mark.parametrize("retry_after", [None, "600", "Fri, 09 Oct 2026 14:12:00 GMT"])
def test_failed_usage_response_is_logged_cached_and_rendered_without_backoff(
    monkeypatch, tmp_path, caplog, surface, retry_after
):
    token = "private-oauth-token"
    monkeypatch.setattr(
        limits,
        "_load_claude_credentials",
        lambda: {"claudeAiOauth": {"accessToken": token}},
    )
    monkeypatch.setattr(
        limits,
        "probe_cli_surface",
        lambda surface, command: SimpleNamespace(
            verdict="ok", version="2.3.4", error=None
        ),
    )
    monkeypatch.setattr(limits, "_cursor_access_token", lambda: token)
    monkeypatch.setattr(limits, "_cursor_tier_from_cli", lambda: {})
    monkeypatch.setattr(
        codex, "app_server_reading", lambda _: (None, "rpc_failed", "rpc_failed")
    )
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    auth = tmp_path / ".codex"
    auth.mkdir()
    (auth / "auth.json").write_text(
        json.dumps(
            {"tokens": {"access_token": token, "account_id": "private-account-id"}}
        )
    )
    response_headers = Message()
    if retry_after is not None:
        response_headers["Retry-After"] = retry_after
    response_headers["anthropic-ratelimit-requests-remaining"] = "0"
    response_headers["anthropic-ratelimit-input-tokens-limit"] = "100000"
    response_headers["X-RateLimit-Reset"] = "2026-10-09T14:12:00Z"
    response_headers["X-RateLimit-Token"] = "other-private-token"
    response_headers["X-RateLimit-Detail"] = f"Bearer {token} private-account-id"
    response_headers["Authorization"] = f"Bearer {token}"
    response_headers["Set-Cookie"] = "private-cookie"
    calls = []

    def fail(request, *, timeout):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(
            request.full_url,
            429,
            "throttled",
            response_headers,
            BytesIO(b"private-response-body"),
        )

    monkeypatch.setattr(urllib.request, "urlopen", fail)
    observed_at = parse_instant("2026-10-09T14:02:00Z")
    readings = limits.observe_plan_limits(
        (surface,),
        state_dir=tmp_path,
        now=observed_at,
        clock=lambda: "2026-10-09T14:02:00Z",
    )
    first_call_count = len(calls)
    cached = limits.observe_plan_limits(
        (surface,), state_dir=tmp_path, now=observed_at + timedelta(seconds=239)
    )
    assert cached == readings
    assert len(calls) == first_call_count
    stored = json.loads((tmp_path / limits.PLAN_LIMIT_CACHE_FILE_NAME).read_text())
    limits.observe_plan_limits(
        (surface,), state_dir=tmp_path, now=observed_at + timedelta(seconds=240)
    )
    assert len(calls) == first_call_count * 2
    assert limits.PLAN_LIMIT_REFRESH_SECONDS == 240

    reading = readings[surface]
    reason = reading["windows"][0]["reason"]
    assert "http_429" in reason
    assert "anthropic-ratelimit-requests-remaining 0" in reason
    assert "anthropic-ratelimit-input-tokens-limit 100000" in reason
    assert "x-ratelimit-reset 2026-10-09T14:12:00Z" in reason
    assert ", at " in reason
    if retry_after:
        assert f"retry-after {retry_after}" in reason
    else:
        assert "retry-after" not in reason
    assert unreadable_guidance(reason) == THROTTLED_GUIDANCE
    assert stored["surfaces"][surface]["windows"][0]["reason"] == reason
    row = MachinePlanLimit(
        machine_id="machine",
        machine_name="machine",
        surface=surface,
        plan_tier=None,
        **reading["windows"][0],
    )
    report = "\n".join(plan_limit_lines((row,), now=reading["observed_at"]))
    assert reason in report
    assert "plan-limit usage-check read failed: http_429" in caplog.text
    evidence = reason + caplog.text + report
    for secret in (
        token,
        "other-private-token",
        "private-cookie",
        "private-response-body",
    ):
        assert secret not in evidence
    if surface == "codex-cli":
        assert "private-account-id" not in evidence
