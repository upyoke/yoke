"""Agent-mode browser approval ends each call and resumes on the next one."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from runtime.api.cli.setup_agent_test_support import AgentDriver, isolate_agent_setup
from yoke_contracts.machine_authorization import (
    HostedMachineAuthorizationDenied,
    HostedMachineCredential,
    PendingMachineAuthorization,
)
from yoke_cli.config import (
    hosted_machine_authorization,
    setup_agent_answers,
    yoke_token_verify,
)
from yoke_cli.transport.bounded_json_http import BoundedJsonHttpResponse

pytest.importorskip("textual")

APPROVAL_KEY = "connect.hosted_machine_approval"
TOKEN = "token-never-shown"
CREDENTIAL = HostedMachineCredential(
    api_url="https://app.upyoke.com/api/orgs/acme", org="acme", token=TOKEN
)
VERIFIED = {
    "ok": True,
    "actor": {"label": "Test Person"},
    "orgs": [{"name": "Acme"}],
    "projects": [],
}


def _pending(code: str) -> PendingMachineAuthorization:
    return PendingMachineAuthorization(
        platform_url="https://app.upyoke.com",
        device_code=f"device-{code}",
        user_code=code,
        verification_uri="https://app.upyoke.com/machine",
        verification_uri_complete=f"https://app.upyoke.com/machine?code={code}",
        expires_in=600,
        interval=5,
    )


class Server:
    """Codes started, and what each one-shot poll answers in turn."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.polls: list[object] = []

    def start(self, *_a, **_k) -> PendingMachineAuthorization:
        self.started.append(f"CODE-{len(self.started) + 1}")
        return _pending(self.started[-1])

    def poll_once(self, pending: PendingMachineAuthorization):
        assert pending.device_code == f"device-{self.started[-1]}"
        answer = self.polls.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer


@pytest.fixture
def server(monkeypatch) -> Server:
    fake = Server()
    monkeypatch.setattr(hosted_machine_authorization, "start", fake.start)
    monkeypatch.setattr(hosted_machine_authorization, "poll_once", fake.poll_once)
    monkeypatch.setattr(
        hosted_machine_authorization,
        "complete",
        lambda *_a, **_k: pytest.fail("agent mode never waits in one call"),
    )
    monkeypatch.setattr(
        hosted_machine_authorization,
        "open_browser",
        lambda *_a: pytest.fail("agent mode never opens a browser"),
    )
    monkeypatch.setattr(yoke_token_verify, "verify", lambda *_a, **_k: VERIFIED)
    return fake


@pytest.fixture
def drive(tmp_path: Path, monkeypatch, capsys) -> AgentDriver:
    isolate_agent_setup(tmp_path, monkeypatch)
    return AgentDriver(capsys)


def _saved() -> dict:
    return json.loads(setup_agent_answers.store_path().read_text(encoding="utf-8"))


def _only_browser(result) -> dict:
    code, lines = result
    assert (code, [line["state"] for line in lines]) == (0, ["browser"]), lines
    return lines[0]


def test_browser_step_ends_the_call_and_the_next_call_continues(drive, server):
    drive()

    browser = _only_browser(drive("connect.destination=hosted"))

    assert browser["key"] == APPROVAL_KEY
    assert browser["human"]["user_code"] == "CODE-1"
    assert browser["wait"]["max_seconds"] == 600
    assert browser["answer_command"].endswith("setup --agent")
    assert "This call has ended" in browser["guidance"]
    saved = _saved()
    assert saved["waiting_key"] == APPROVAL_KEY
    assert saved["pending_approval"]["device_code"] == "device-CODE-1"
    mode = os.stat(setup_agent_answers.store_path()).st_mode
    assert stat.S_IMODE(mode) == setup_agent_answers.STORE_MODE
    assert "device-CODE-1" not in drive.stderr
    setup_agent_answers.open_store().release()  # the lock is free again

    server.polls = [None, CREDENTIAL]
    browser = _only_browser(drive())
    assert browser["human"]["user_code"] == "CODE-1"

    code, lines = drive()

    assert (code, lines[-1]["key"]) == (0, "github.machine"), lines
    assert server.started == ["CODE-1"]
    stored = setup_agent_answers.store_path().read_text(encoding="utf-8")
    assert _saved()["pending_approval"] is None
    assert "device-CODE-1" not in stored and TOKEN not in stored


def test_a_denial_mints_one_fresh_code_then_asks(drive, server):
    drive()
    _only_browser(drive("connect.destination=hosted"))
    server.polls = [HostedMachineAuthorizationDenied("authorization_denied: denied")]

    browser = _only_browser(drive())

    assert browser["human"]["user_code"] == "CODE-2"
    assert _saved()["pending_approval"]["after_denial"] is True

    server.polls = [HostedMachineAuthorizationDenied("authorization_denied: denied")]
    code, lines = drive()

    assert (code, lines[-1]["key"]) == (0, "connect.hosted_machine_error"), lines
    assert _saved()["pending_approval"] is None
    assert server.started == ["CODE-1", "CODE-2"]


def test_an_expired_code_asks_for_a_fresh_one_without_the_server(drive, monkeypatch):
    monkeypatch.setattr(
        hosted_machine_authorization, "start", lambda *_a, **_k: _pending("CODE-1")
    )
    monkeypatch.setattr(
        hosted_machine_authorization,
        "request_json",
        lambda *_a, **_k: pytest.fail("an expired code is never polled"),
    )
    drive()
    _only_browser(drive("connect.destination=hosted"))
    record = _saved()
    record["pending_approval"]["expires_at"] = 0
    setup_agent_answers._write_private(
        setup_agent_answers.store_path(), json.dumps(record)
    )

    code, lines = drive()

    assert (code, lines[-1]["key"]) == (0, "connect.hosted_machine_error"), lines
    assert "authorization_expired" in " ".join(lines[-1]["detail"])
    assert _saved()["pending_approval"] is None


@pytest.mark.parametrize(
    ("status", "payload", "approved"),
    [
        (202, {"error": "authorization_pending"}, False),
        (
            200,
            {
                "token": "t",
                "org": "acme",
                "api_url": "https://app.upyoke.com/api/orgs/acme",
            },
            True,
        ),
    ],
)
def test_poll_once_asks_once(monkeypatch, status, payload, approved):
    calls = []

    def fake_request(*_a, **_k):
        calls.append(1)
        return BoundedJsonHttpResponse(payload=payload, status=status, headers={})

    monkeypatch.setattr(hosted_machine_authorization, "request_json", fake_request)
    monkeypatch.setattr(
        hosted_machine_authorization,
        "_machine_identity",
        lambda: {"machine_id": "m", "machine_name": "n"},
    )

    credential = hosted_machine_authorization.poll_once(_pending("K7F2"))

    assert calls == [1]
    assert (credential is not None) is approved
