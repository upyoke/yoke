"""Clients collect an approval made before expiry, even when they ask after it."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.cli.setup_agent_test_support import AgentDriver, isolate_agent_setup
from runtime.api.cli.test_setup_agent_approvals import (
    TOKEN,
    VERIFIED,
    _only_browser,
    _pending,
    _saved,
)
from yoke_contracts.machine_authorization import HostedMachineAuthorizationError
from yoke_cli.config import (
    hosted_machine_authorization,
    setup_agent_answers,
    yoke_token_verify,
)
from yoke_cli.transport.bounded_json_http import BoundedJsonHttpResponse

pytest.importorskip("textual")

APPROVED = {
    "token": TOKEN,
    "org": "acme",
    "api_url": "https://app.upyoke.com/api/orgs/acme",
}
UNCOLLECTED = {
    "error": "authorization_expired",
    "message": "authorization_expired: approval_uncollected: this code was approved "
    "before it expired; start a fresh connection code",
}


@pytest.fixture
def answers(monkeypatch) -> list[tuple[int, dict]]:
    replies: list[tuple[int, dict]] = []

    def request(*_a, **_k):
        status, payload = replies.pop(0)
        return BoundedJsonHttpResponse(payload=payload, status=status, headers={})

    monkeypatch.setattr(hosted_machine_authorization, "request_json", request)
    monkeypatch.setattr(
        hosted_machine_authorization,
        "_machine_identity",
        lambda: {"machine_id": "m", "machine_name": "n"},
    )
    return replies


@pytest.fixture
def drive(tmp_path: Path, monkeypatch, capsys) -> AgentDriver:
    isolate_agent_setup(tmp_path, monkeypatch)
    monkeypatch.setattr(
        hosted_machine_authorization, "start", lambda *_a, **_k: _pending("CODE-1")
    )
    monkeypatch.setattr(yoke_token_verify, "verify", lambda *_a, **_k: VERIFIED)
    return AgentDriver(capsys)


def _lapse_saved_code() -> None:
    record = _saved()
    record["pending_approval"]["expires_at"] = 0
    setup_agent_answers._write_private(
        setup_agent_answers.store_path(), json.dumps(record)
    )


def test_agent_setup_collects_a_lapsed_code_approved_in_time(drive, answers):
    drive()
    _only_browser(drive("connect.destination=hosted"))
    _lapse_saved_code()
    answers.append((200, APPROVED))

    code, lines = drive()

    assert (code, lines[-1]["key"]) == (0, "github.machine"), lines
    assert answers == []
    assert _saved()["pending_approval"] is None


def test_agent_setup_names_an_approval_collected_too_late(drive, answers):
    drive()
    _only_browser(drive("connect.destination=hosted"))
    _lapse_saved_code()
    answers.append((410, UNCOLLECTED))

    code, lines = drive()

    assert (code, lines[-1]["key"]) == (0, "connect.hosted_machine_error"), lines
    detail = " ".join(lines[-1]["detail"])
    assert "authorization_expired: approval_uncollected" in detail
    assert "authorization_expired: authorization_expired" not in detail
    assert _saved()["pending_approval"] is None


def _wait(answers, replies) -> object:
    answers.extend(replies)
    clock = [0.0]
    return hosted_machine_authorization.complete(
        _pending("K7F2"),
        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
        monotonic=lambda: clock[0],
    )


def test_wizard_wait_polls_once_more_at_expiry(answers):
    pending = (202, {"error": "authorization_pending"})
    # Interval 5s over 600s: 119 polls inside the window, then the final one.
    credential = _wait(answers, [pending] * 119 + [(200, APPROVED)])

    assert credential.token == TOKEN
    assert answers == []


def test_wizard_wait_ends_with_the_servers_expiry_reason(answers):
    pending = (202, {"error": "authorization_pending"})
    with pytest.raises(HostedMachineAuthorizationError, match="approval_uncollected"):
        _wait(answers, [pending] * 119 + [(410, UNCOLLECTED)])
