"""Agent setup refusals wait at the question they repeat.

Machine state can change between calls so a stored answer no longer fits its
screen; the run then stops at that earlier question, not the one it was
waiting at. The refusal prints that question with its answer command, and
that exact answer must be accepted on the next call.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.cli.setup_agent_test_support import (
    MACHINE_ONLY_ANSWERS,
    AgentDriver,
    isolate_agent_setup,
)
from yoke_cli.config import local_universe_setup

pytest.importorskip("textual")


@pytest.fixture
def drive(tmp_path: Path, monkeypatch, capsys) -> AgentDriver:
    isolate_agent_setup(tmp_path, monkeypatch)
    return AgentDriver(capsys)


def test_the_answer_a_refusal_prints_is_accepted_next(drive, monkeypatch):
    drive.walk(MACHINE_ONLY_ANSWERS[:3])
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
