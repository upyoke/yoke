"""Agent setup refusals wait at the question they repeat.

Machine state can change between calls so a stored answer no longer fits its
screen; the run then stops at that earlier question, not the one it was
waiting at. The refusal prints that question with its answer command, and
that exact answer must be accepted on the next call. A question the run
stopped at must be reached again: the machine approval's error question is
saved, so its answer runs once and is never refused after a fresh approval.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.cli.setup_agent_test_support import (
    MACHINE_ONLY_ANSWERS,
    AgentDriver,
    isolate_agent_setup,
)
from runtime.api.cli.test_setup_agent_approvals import Server
from yoke_cli.config import hosted_machine_authorization, local_universe_setup

pytest.importorskip("textual")


@pytest.fixture
def drive(tmp_path: Path, monkeypatch, capsys) -> AgentDriver:
    isolate_agent_setup(tmp_path, monkeypatch)
    return AgentDriver(capsys)


@pytest.fixture
def server(monkeypatch) -> Server:
    fake = Server()
    monkeypatch.setattr(hosted_machine_authorization, "start", fake.start)
    monkeypatch.setattr(hosted_machine_authorization, "poll_once", fake.poll_once)
    return fake


def test_the_answer_a_refusal_prints_is_accepted_next(drive, monkeypatch):
    drive.walk(MACHINE_ONLY_ANSWERS[:4])
    monkeypatch.setattr(
        local_universe_setup,
        "inspect_local_state",
        lambda *_a, **_k: {"state": local_universe_setup.LOCAL_UNIVERSE_VERIFY},
    )

    code, lines = drive("github.machine=skip")
    refused = lines[-1]
    assert (code, refused["state"]) == (2, "refused")
    assert refused["reason"] == "setup_answer_not_current"
    assert refused["key"] == "connect.local_universe"
    assert "continue" in {row["value"] for row in refused["answers"]}

    code, lines = drive("connect.local_universe=continue")

    assert (code, lines[-1]["state"]) == (0, "question"), lines
    assert lines[-1]["key"] == "github.machine"


def test_a_retry_answer_starts_one_approval_and_returns_it(drive, server):
    drive("project.mode=machine-only")
    drive("connect.destination=hosted")
    server.polls = [RuntimeError("authorization_expired: the code expired")]
    code, lines = drive()
    assert (code, lines[-1]["key"]) == (0, "connect.hosted_machine_error"), lines
    assert drive() == (code, lines)  # a bare call asks again and starts nothing

    code, lines = drive("connect.hosted_machine_error=retry")

    assert (code, lines[-1]["state"]) == (0, "browser"), lines
    assert lines[-1]["human"]["user_code"] == "CODE-2"
    assert server.started == ["CODE-1", "CODE-2"]


def test_back_from_the_approval_error_starts_nothing(drive, server):
    drive("project.mode=machine-only")
    drive("connect.destination=hosted")
    server.polls = [RuntimeError("authorization_expired: the code expired")]
    drive("project.mode=machine-only")

    code, lines = drive("connect.hosted_machine_error=back")

    assert (code, lines[-1]["key"]) == (0, "connect.destination"), lines
    assert server.started == ["CODE-1"]
    code, lines = drive("connect.destination=hosted")
    assert (code, lines[-1]["human"]["user_code"]) == (0, "CODE-2"), lines
