"""The public adoption adapter preserves the exact execution subject."""

from types import SimpleNamespace

import pytest

from yoke_cli.commands.qa_case import TOOL_COMMANDS, qa_plan_adopt
from yoke_core.domain import qa_plan_execution_adopt_cli as cli
from yoke_core.domain.qa_plan_execution import QaPlanExecutionError


@pytest.mark.parametrize(
    "arguments,kind",
    [
        (["--item", "PREFIX-42"], "item"),
        ([], "global"),
    ],
)
def test_adopt_dispatches_registered_function_with_exact_subject(
    monkeypatch, capsys, arguments, kind
):
    calls = []
    monkeypatch.setattr(
        cli, "build_actor", lambda **_: SimpleNamespace(session_id="successor")
    )

    def call(**kwargs):
        calls.append(kwargs)
        return {"execution_id": "saved-capture", "state": "adopted"}

    monkeypatch.setattr(cli, "_call_plan_function", call)
    assert (
        cli.main(
            [*arguments, "--execution-id", "saved-capture", "--reason", "Restaffed QA"]
        )
        == 0
    )
    assert calls[0]["function_id"] == "qa.plan_execution.adopt"
    assert calls[0]["target"].kind == kind
    assert calls[0]["payload"] == {
        "execution_id": "saved-capture",
        "reason": "Restaffed QA",
    }
    assert '"state": "adopted"' in capsys.readouterr().out
    assert TOOL_COMMANDS[("qa", "plan", "adopt")] is qa_plan_adopt


def test_adopt_serving_floor_refusal_is_visible(monkeypatch, capsys):
    monkeypatch.setattr(
        cli, "build_actor", lambda **_: SimpleNamespace(session_id="successor")
    )

    def call(**_):
        raise QaPlanExecutionError(
            "function_requires_newer_server: ask control-plane operator to serve the required release"
        )

    monkeypatch.setattr(cli, "_call_plan_function", call)
    assert (
        cli.main(
            [
                "--item",
                "PREFIX-42",
                "--execution-id",
                "capture",
                "--reason",
                "Restaffed QA",
            ]
        )
        == 2
    )
    assert "function_requires_newer_server" in capsys.readouterr().err
