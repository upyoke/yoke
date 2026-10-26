"""Human mutation receipts stay small while machine results stay complete."""

import io
import json

import pytest

from yoke_cli.commands.adapters import (
    db,
    items_create_dispatch,
    sessions_touch as sessions,
)
from yoke_cli.commands.adapters.session_control_launch_output import write_launch_result
from yoke_cli.transport.public_ref_display import emit_response
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionWarning


def response(function, result):
    return FunctionCallResponse(
        function=function,
        version="v1",
        request_id="receipt-test",
        success=True,
        result=result,
        warnings=[FunctionWarning(code="notice", step="test", detail="retained")],
    )


@pytest.mark.parametrize("reason", [None, "waiting for CI", "waiting\nfor CI"])
def test_touch_one_line_and_json_preserves_session(monkeypatch, capsys, reason):
    row = {
        "session_id": "session-example",
        "mode": "dash",
        "last_heartbeat": "2026-10-26T12:00:00Z",
        "quiet_reason": reason,
        "workspace": "/example",
        "other_state": "x" * 10000,
    }
    reply = response("sessions.touch", {"success": True, "session": row})

    def dispatch(**kw):
        return emit_response(
            reply, json_mode=kw["json_mode"], human_writer=kw["human_writer"]
        )

    monkeypatch.setattr(sessions, "dispatch_and_emit", dispatch)
    assert sessions.sessions_touch(["--mode", "dash"]) == 0
    captured = capsys.readouterr()
    assert len(captured.out.splitlines()) == 1
    assert "session-example" in captured.out and "dash" in captured.out
    assert row["last_heartbeat"] in captured.out
    assert ("reason:" in captured.out) is bool(reason)
    assert "other_state" not in captured.out
    assert "notice" in captured.err
    assert sessions.sessions_touch(["--json"]) == 0
    assert json.loads(capsys.readouterr().out)["result"] == reply.result


@pytest.mark.parametrize("preview", [False, True])
def test_create_instruction_count_does_not_add_lines(monkeypatch, capsys, preview):
    monkeypatch.setattr(
        items_create_dispatch._helpers, "ensure_handlers_loaded", lambda: None
    )
    counts = []
    for count in (1, 20):
        instructions = [
            {"id": f"rule-{n:02}", "content": "Long instruction\n" * 20}
            for n in range(count)
        ]
        reply = response(
            "items.create",
            {
                "public_ref": "-".join(("APP", "7")),
                "spec_accepted": True,
                "execution_instructions": instructions,
            },
        )
        monkeypatch.setattr(
            items_create_dispatch, "call_dispatcher", lambda **kw: reply
        )

        def dispatch(**kw):
            return emit_response(
                reply, json_mode=kw["json_mode"], human_writer=kw["human_writer"]
            )

        monkeypatch.setattr(
            items_create_dispatch._helpers, "dispatch_and_emit", dispatch
        )
        args = dict(target=None, payload={"dry_run": preview}, session_id=None)
        assert items_create_dispatch.dispatch_create(**args, json_mode=False) == 0
        output = capsys.readouterr()
        counts.append(len(output.out.splitlines()))
        for rule in instructions:
            assert output.out.count(rule["id"]) == 1
        assert "Long instruction" not in output.out
        assert "notice" in output.err
        assert items_create_dispatch.dispatch_create(**args, json_mode=True) == 0
        assert json.loads(capsys.readouterr().out)["result"] == reply.result
    assert counts[0] == counts[1]


@pytest.mark.parametrize(
    "function,writer,result",
    [
        ("db.read.run", None, {"columns": ["a"], "rows": [["one"], ["two"]]}),
        (
            "session_control.launch.create",
            lambda reply, out, err: write_launch_result(reply.result, out),
            {
                "launch": {
                    "launch_id": "launch-example",
                    "level_placement": {"candidates": [{"label": "candidate"}]},
                }
            },
        ),
    ],
)
def test_json_retains_complete_result(capsys, function, writer, result):
    reply = response(function, result)
    assert emit_response(reply, json_mode=True, human_writer=writer) == 0
    assert json.loads(capsys.readouterr().out)["result"] == result


def test_db_machine_formats_stay_exact():
    reply = response(
        "db.read.run", {"columns": ["a", "b"], "rows": [[1, "two"], [3, "four"]]}
    )
    out, err = io.StringIO(), io.StringIO()
    db._write_lines(reply, out, err)
    assert out.getvalue() == "1|two\n3|four\n"
    out = io.StringIO()
    db._write_json(reply, out, err)
    assert json.loads(out.getvalue()) == reply.result
