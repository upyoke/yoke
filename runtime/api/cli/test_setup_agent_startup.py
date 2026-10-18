"""Agent setup makes progress without an asyncio worker or event loop."""

import asyncio

import pytest

from yoke_cli.config.onboard_wizard_path import PathFlow
from yoke_cli.config import setup_agent_answers

from runtime.api.cli.setup_agent_test_support import (
    AgentDriver,
    MACHINE_ONLY_ANSWERS,
    isolate_agent_setup,
)


def test_install_progress_precedes_check_and_apply_needs_no_event_loop(
    tmp_path, monkeypatch, capsys
):
    fake = isolate_agent_setup(tmp_path, monkeypatch)

    def no_loop(*args, **kwargs):
        pytest.fail("agent setup must not start an event loop")

    monkeypatch.setattr(asyncio, "run", no_loop)
    monkeypatch.setattr(asyncio, "to_thread", no_loop)
    check = PathFlow._check_install
    checks = []

    def install(shell):
        captured = capsys.readouterr()
        assert captured.err.startswith("Checking install…\n")
        assert not captured.out
        checks.append(True)
        return check(shell)

    monkeypatch.setattr(PathFlow, "_check_install", install)
    driver = AgentDriver(capsys)
    assert driver.walk(MACHINE_ONLY_ANSWERS)[1][-1]["key"] == "review.confirm"
    code, events = driver("review.confirm=apply")
    assert code == 0
    assert events[-1]["state"] == "done"
    assert fake.applied
    assert len(checks) == len(MACHINE_ONLY_ANSWERS) + 2


def test_interrupted_install_names_result_and_preserves_saved_answers(
    tmp_path, monkeypatch, capsys
):
    isolate_agent_setup(tmp_path, monkeypatch)
    driver = AgentDriver(capsys)
    assert driver()[0] == 0
    saved = setup_agent_answers.store_path().read_bytes()

    def interrupt(shell):
        raise KeyboardInterrupt

    monkeypatch.setattr(PathFlow, "_check_install", interrupt)
    code, events = driver()
    assert code == 1
    assert events[-1]["reason"] == "setup_interrupted"
    assert "continue" in events[-1]["recovery"]
    assert setup_agent_answers.store_path().read_bytes() == saved
    assert "Traceback" not in driver.stderr
