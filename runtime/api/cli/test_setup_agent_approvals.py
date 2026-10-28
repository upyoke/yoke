"""Agent-mode browser approvals end each call and resume on the next one."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from runtime.api.cli.setup_agent_test_support import (
    MACHINE_ONLY_ANSWERS,
    AgentDriver,
    isolate_agent_setup,
)
from yoke_contracts.machine_authorization import (
    HostedMachineAuthorizationDenied,
    HostedMachineCredential,
    PendingMachineAuthorization,
)
from yoke_cli.config import (
    github_device_flow,
    github_machine,
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
    drive("project.mode=machine-only")

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
    drive("project.mode=machine-only")
    _only_browser(drive("connect.destination=hosted"))
    server.polls = [HostedMachineAuthorizationDenied("authorization_denied: denied")]

    browser = _only_browser(drive())

    assert browser["human"]["user_code"] == "CODE-2"
    assert _saved()["pending_approval"]["after_denial"] is True

    server.polls = [HostedMachineAuthorizationDenied("authorization_denied: denied")]
    code, lines = drive()

    assert (code, lines[-1]["key"]) == (0, "connect.hosted_machine_error"), lines
    error = {"kind": "machine", "error": "authorization_denied: denied"}
    assert _saved()["pending_approval"] == error
    assert server.started == ["CODE-1", "CODE-2"]


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


GITHUB_TOKEN = {"access_token": "gh-token-never-shown"}


class GitHub:
    """A ``github_machine.connect`` that runs the shell's device step."""

    def __init__(self) -> None:
        self.started: list[str] = []
        self.polls: list[object] = []

    def start(self, **_kw) -> github_device_flow.DeviceAuthorization:
        self.started.append(f"ABCD-{len(self.started) + 1:04d}")
        return github_device_flow.DeviceAuthorization(
            device_code=f"gh-device-{len(self.started)}",
            user_code=self.started[-1],
            verification_uri="https://github.com/login/device",
            expires_in=900,
            interval=5,
        )

    def poll_once(self, device, **_kw):
        assert device.device_code == f"gh-device-{len(self.started)}"
        answer = self.polls.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    def connect(self, *, device_authorize, **_kw) -> dict:
        try:
            result = device_authorize(
                client_id="client", web_url="https://github.com", opener=None
            )
        except github_device_flow.GitHubDeviceFlowError as exc:
            raise github_machine.GitHubMachineError(str(exc)) from exc
        assert result.token_response == GITHUB_TOKEN
        return {"ok": True, "ready": True, "configured": True}


@pytest.fixture
def github(monkeypatch) -> GitHub:
    fake = GitHub()
    monkeypatch.setattr(github_device_flow, "start", fake.start)
    monkeypatch.setattr(github_device_flow, "poll_once", fake.poll_once)
    monkeypatch.setattr(github_machine, "connect", fake.connect)
    return fake


def _to_github(drive: AgentDriver) -> None:
    drive.walk(MACHINE_ONLY_ANSWERS[:4])


def test_github_sign_in_ends_the_call_and_resumes(drive, github):
    _to_github(drive)

    browser = _only_browser(drive("github.machine=connect"))

    assert (browser["key"], browser["human"]["user_code"]) == (
        "github.machine",
        "ABCD-0001",
    )
    assert browser["wait"]["max_seconds"] == 900
    assert _saved()["pending_approval"]["kind"] == "github"
    github.polls = [None, GITHUB_TOKEN]
    assert _only_browser(drive())["human"]["user_code"] == "ABCD-0001"

    code, lines = drive()

    assert (code, lines[-1]["key"]) == (0, "review.confirm"), lines
    assert github.started == ["ABCD-0001"]
    assert _saved()["pending_approval"] is None
    assert "gh-device-1" not in setup_agent_answers.store_path().read_text()


def test_github_sign_in_left_for_later_forgets_its_code(drive, github):
    _to_github(drive)
    _only_browser(drive("github.machine=connect"))

    code, lines = drive("github.machine=skip")

    assert (code, lines[-1]["key"]) == (0, "review.confirm"), lines
    assert _saved()["pending_approval"] is None


def test_a_lapsed_github_code_asks_by_name(drive, github):
    _to_github(drive)
    _only_browser(drive("github.machine=connect"))
    github.polls = [
        github_device_flow.GitHubDeviceFlowError(
            "github_device_authorization_expired: GitHub device authorization expired"
        )
    ]

    code, lines = drive()

    assert (code, lines[-1]["key"]) == (0, "github.machine_github_error"), lines
    assert "github_device_authorization_expired" in json.dumps(lines[-1])
    assert _saved()["pending_approval"] is None


def test_github_poll_once_refuses_a_lapsed_code_without_github(monkeypatch):
    monkeypatch.setattr(
        github_device_flow.github_device_transport,
        "post_form",
        lambda *_a, **_k: pytest.fail("a lapsed code is never polled"),
    )
    device = github_device_flow.DeviceAuthorization(
        device_code="d",
        user_code="ABCD-0001",
        verification_uri="u",
        expires_in=0,
        interval=5,
    )

    with pytest.raises(github_device_flow.GitHubDeviceFlowError, match="expired"):
        github_device_flow.poll_once(
            device, client_id="c", web_url="https://github.com"
        )


@pytest.mark.parametrize("kind", ["machine", "github"])
def test_new_approval_survives_a_later_refusal(drive, server, github, monkeypatch, kind):
    from yoke_cli.config.setup_agent_answering import SetupRefusal
    from yoke_cli.config.setup_agent_shell import AgentSetup

    if kind == "github":
        _to_github(drive)
    else:
        drive("project.mode=machine-only")
    before = _saved()["answers"]

    def refuse(_self, prompt):
        raise SetupRefusal("setup_answer_not_current", "answer the current key", prompt)

    original = AgentSetup._refuse_unused_answers
    monkeypatch.setattr(AgentSetup, "_refuse_unused_answers", refuse)
    answer = "github.machine=connect" if kind == "github" else "connect.destination=hosted"
    code, lines = drive(answer)

    assert (code, lines[-1]["reason"]) == (2, "setup_answer_not_current")
    saved = _saved()
    assert saved["pending_approval"]["kind"] == kind
    expected = "gh-device-1" if kind == "github" else "device-CODE-1"
    assert saved["pending_approval"]["device_code"] == expected
    assert saved["answers"] == before

    monkeypatch.setattr(AgentSetup, "_refuse_unused_answers", original)
    server.polls = github.polls = [None]
    drive()  # Re-ask the unanswered choice before replaying the saved approval.
    browser = _only_browser(drive(answer))
    assert browser["human"]["user_code"] == saved["pending_approval"]["user_code"]
    assert len(server.started if kind == "machine" else github.started) == 1
