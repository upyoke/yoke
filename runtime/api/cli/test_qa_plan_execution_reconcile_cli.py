"""The public reconcile adapter targets the named project and execution."""

from types import SimpleNamespace

import pytest

from yoke_cli.commands.qa_case import TOOL_COMMANDS, USAGE, qa_plan_reconcile
from yoke_core.domain import qa_plan_execution_reconcile_cli as cli
from yoke_core.domain.qa_plan_execution import QaPlanExecutionError

ARGS = ["--project", "yoke", "--execution-id", "stranded", "--reason", "owner ended"]


def _actor(monkeypatch):
    monkeypatch.setattr(
        cli, "build_actor", lambda **_: SimpleNamespace(session_id="steering")
    )


def test_reconcile_dispatches_registered_function_on_project_target(
    monkeypatch, capsys
):
    _actor(monkeypatch)
    calls = []

    def call(**kwargs):
        calls.append(kwargs)
        return {"execution_id": "stranded", "outcome": "aborted"}

    monkeypatch.setattr(cli, "_call_plan_function", call)
    assert cli.main(ARGS) == 0
    assert calls[0]["function_id"] == "qa.plan_execution.reconcile"
    assert calls[0]["target"].kind == "global"
    assert calls[0]["target"].project_id == "yoke"
    assert calls[0]["payload"] == {"execution_id": "stranded", "reason": "owner ended"}
    assert '"outcome": "aborted"' in capsys.readouterr().out
    assert TOOL_COMMANDS[("qa", "plan", "reconcile")] is qa_plan_reconcile
    assert "--execution-id ID --reason TEXT" in USAGE["yoke qa plan reconcile"]


def test_reconcile_refusal_stays_visible(monkeypatch, capsys):
    _actor(monkeypatch)

    def call(**_):
        raise QaPlanExecutionError(
            "steering_seat_required: acquire the covering steering seat"
        )

    monkeypatch.setattr(cli, "_call_plan_function", call)
    assert cli.main(ARGS) == 2
    assert "steering_seat_required" in capsys.readouterr().err


def test_overlong_reason_refuses_before_dispatch(monkeypatch, capsys):
    _actor(monkeypatch)
    monkeypatch.setattr(cli, "_call_plan_function", pytest.fail)
    with pytest.raises(SystemExit):
        cli.main([*ARGS[:4], "--reason", "x" * 201])
    assert "reconcile_reason_too_long" in capsys.readouterr().err
