"""Agent setup started with ``--connect`` asks for browser approval at most once."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.cli.setup_agent_test_support import AgentDriver, isolate_agent_setup
from yoke_cli.config import (
    hosted_machine_authorization,
    machine_config,
    writer,
    yoke_token_verify,
)

pytest.importorskip("textual")

CONNECT = ("--connect", "https://app.upyoke.com")
TOKEN = "token-never-shown"
VERIFIED = {
    "ok": True,
    "actor": {"label": "Test Person"},
    "orgs": [{"name": "Acme"}],
    "projects": [],
}


@pytest.fixture
def agent(tmp_path: Path, monkeypatch, capsys):
    isolate_agent_setup(tmp_path, monkeypatch)
    return AgentDriver(capsys)


@pytest.fixture
def approvals(monkeypatch) -> list[str]:
    """Record each device approval the setup starts."""
    from yoke_contracts.machine_authorization import (
        HostedMachineCredential,
        PendingMachineAuthorization,
    )

    started: list[str] = []

    def start(*_a, **_k):
        code = f"CODE-{len(started) + 1}"
        started.append(code)
        return PendingMachineAuthorization(
            platform_url="https://app.upyoke.com",
            device_code=f"device-{code}",
            user_code=code,
            verification_uri="https://app.upyoke.com/machine",
            verification_uri_complete=f"https://app.upyoke.com/machine?code={code}",
            expires_in=600,
            interval=5,
        )

    credential = HostedMachineCredential(
        api_url="https://app.upyoke.com/api/orgs/acme", org="acme", token=TOKEN
    )
    monkeypatch.setattr(hosted_machine_authorization, "start", start)
    monkeypatch.setattr(
        hosted_machine_authorization, "complete", lambda *_a, **_k: credential
    )
    monkeypatch.setattr(
        hosted_machine_authorization,
        "open_browser",
        lambda *_a: pytest.fail("agent mode never opens a browser"),
    )
    monkeypatch.setattr(yoke_token_verify, "verify", lambda *_a, **_k: VERIFIED)
    return started


def _states(lines: list[dict]) -> list[str]:
    return [line["state"] for line in lines]


def _answer_to_review(drive: AgentDriver) -> None:
    for answer, next_key in (
        ("github.machine=skip", "project.mode"),
        ("project.mode=machine-only", "review.confirm"),
    ):
        code, lines = drive(answer)
        assert (code, _states(lines), lines[-1]["key"]) == (
            0,
            ["question"],
            next_key,
        ), lines


def test_first_connect_prints_one_approval_and_later_answers_reuse_it(agent, approvals):
    code, lines = agent(flags=CONNECT)

    assert (code, _states(lines)) == (0, ["browser", "question"]), lines
    assert lines[0]["human"]["user_code"] == "CODE-1"
    assert lines[-1]["key"] == "github.machine"

    _answer_to_review(agent)
    assert approvals == ["CODE-1"]


def test_stored_connection_answers_advance_without_a_new_approval(agent, approvals):
    writer.set_connection(
        "acme",
        transport="https",
        api_url="https://app.upyoke.com/api/orgs/acme",
        token=TOKEN,
        activate=True,
        path=str(machine_config.config_path(None)),
    )

    code, lines = agent(flags=CONNECT)

    assert (code, _states(lines), lines[-1]["key"]) == (
        0,
        ["question"],
        "github.machine",
    ), lines
    _answer_to_review(agent)
    assert approvals == []
