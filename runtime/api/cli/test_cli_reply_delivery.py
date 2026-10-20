"""Complete human delivery and unchanged deliberate machine envelopes."""

import json

import pytest

from yoke_cli.commands.command_tree import command_routes
from yoke_cli.transport.public_ref_display import emit_response
from yoke_cli.transport.output_limit import REPLY_LIMIT_BYTES
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
    FunctionWarning,
)


def response(function, result):
    return FunctionCallResponse(
        success=True, function=function, version="v1", result=result
    )


@pytest.mark.parametrize(
    "route,function",
    [
        (" ".join(route), fid or "client-local")
        for route, (fid, _) in sorted(command_routes().items())
    ],
)
def test_each_registered_response_boundary(route, function, capsys):
    # These are shared-boundary fixtures, not live adapter executions.
    for result, expected in [
        (
            {"public_ref": "APP-7", "status": "ready", "scope": "checkout"},
            "status: ready",
        ),
        ({"rows": []}, "rows: no entries."),
    ]:
        assert emit_response(response(function, result), json_mode=False) == 0
        output = capsys.readouterr()
        assert expected in output.out, route
        assert len((output.out + output.err).encode()) <= REPLY_LIMIT_BYTES
        assert emit_response(response(function, result), json_mode=True, full=True) == 0
        assert json.loads(capsys.readouterr().out)["result"] == result
    denied = response(function, {}).model_copy(
        update={
            "success": False,
            "error": FunctionError(
                code="permission_denied",
                message="Caller lacks authority.",
                recovery_hint="Ask the project owner to grant access.",
            ),
        }
    )
    assert emit_response(denied, json_mode=False) == 1
    output = capsys.readouterr()
    assert "permission_denied" in output.err
    assert "Ask the project owner" in output.err
    assert "project_required" not in output.err
    large = {"body": "record\n" * 800}
    assert emit_response(response(function, large), json_mode=False) == 0
    assert "record" in capsys.readouterr().out
    assert emit_response(response(function, large), json_mode=True) == 0
    assert json.loads(capsys.readouterr().out)["result"] == large


def test_large_write_receipt_preserves_instructions_and_warnings(capsys):
    payload = {"body": "receipt " * 10_000, "execution_instructions": [{"content": "Read the pinned workflow."}], "handoff": {"next_command": "/yoke polish APP-7"}}
    receipt = response("sessions.touch", payload).model_copy(update={"warnings": [FunctionWarning(code="pending", step="publish", detail="Publication pending.")]})
    assert emit_response(receipt, json_mode=False) == 0
    output = capsys.readouterr()
    assert payload["body"] in output.out
    assert "Read the pinned workflow" in output.out
    assert "/yoke polish APP-7" in output.out
    assert "Publication pending." in output.err


def test_custom_writer_keeps_server_warnings(capsys):
    receipt = response("items.create", {"public_ref": "APP-7"}).model_copy(
        update={
            "warnings": [
                FunctionWarning(
                    code="pending", step="publish", detail="Not yet published."
                )
            ]
        }
    )
    assert (
        emit_response(
            receipt,
            json_mode=False,
            human_writer=lambda r, out, err: out.write("Created APP-7.\n"),
        )
        == 0
    )
    output = capsys.readouterr()
    assert "Created APP-7" in output.out
    assert "Not yet published." in output.err


def test_silent_human_writer_delivers_explicit_empty_state(capsys):
    assert (
        emit_response(
            response("items.update", {}),
            json_mode=False,
            human_writer=lambda receipt, out, err: None,
        )
        == 0
    )
    assert "Result: empty." in capsys.readouterr().out


def test_multiline_write_is_complete(capsys):
    payload = {"body": "\n".join(["x" * 81] * 200)}
    assert emit_response(response("items.create", payload), json_mode=False) == 0
    assert payload["body"] in capsys.readouterr().out


def test_explicit_line_protocol_remains_complete(capsys):
    from yoke_cli.commands.adapters.db import _write_lines

    payload = {"columns": ["name"], "rows": [[str(i)] for i in range(1000)]}
    assert (
        emit_response(
            response("db.read.run", payload),
            json_mode=False,
            human_writer=_write_lines,
            machine_mode=True,
            full=True,
        )
        == 0
    )
    assert capsys.readouterr().out.splitlines() == [str(i) for i in range(1000)]


def test_empty_local_receipt_is_labeled(capsys):
    from yoke_cli.commands.adapters.config_write_shared import run

    assert run(lambda: {"connections": []}) == 0
    assert "connections: no entries." in capsys.readouterr().out


@pytest.mark.parametrize("owner", ["project_onboard", "packs"])
def test_local_report_owners_preserve_large_and_machine_replies(owner, capsys):
    from importlib import import_module

    module = import_module("yoke_cli.commands.adapters." + owner)
    emit = module._emit if owner == "project_onboard" else module._emit_report
    payload = {"rows": [{"name": str(i)} for i in range(2000)]}
    emit(payload, False)
    output = capsys.readouterr()
    assert "1999" in output.out
    emit(payload, True)
    assert json.loads(capsys.readouterr().out) == payload


def test_prd_report_owner_keeps_warning_and_refusal(capsys):
    from yoke_cli.commands.adapters.readiness import _emit_prd_validate

    receipt = response(
        "readiness.prd_validate.run", {"report_text": "Checks: complete"}
    )
    receipt = receipt.model_copy(
        update={
            "warnings": [
                FunctionWarning(
                    code="pending", step="publish", detail="Publication pending."
                )
            ]
        }
    )
    assert _emit_prd_validate(receipt, json_mode=False) == 0
    output = capsys.readouterr()
    assert "Checks: complete" in output.out
    assert "Publication pending." in output.err


def test_delimiter_in_a_value_keeps_unambiguous_field_labels(capsys):
    assert (
        emit_response(
            response(
                "db.read.run",
                {"rows": [{"name": "A | B", "command": "build | deploy"}]},
            ),
            json_mode=False,
        )
        == 0
    )
    output = capsys.readouterr().out
    assert "name: A | B" in output
    assert "command: build | deploy" in output


def test_local_core_logs_keep_complete_evidence_and_immediate_recovery(capsys):
    from yoke_cli.commands.core import _emit

    payload = {
        "ok": False,
        "action": "logs",
        "logs": {"api": "entry\n" * 1000},
        "issues": [
            {
                "code": "runtime_missing",
                "message": "Runtime absent.",
                "guidance": "Install the runtime before starting core.",
            }
        ],
    }
    assert _emit(payload, False) == 1
    output = capsys.readouterr()
    assert "runtime_missing" in output.out
    assert "Install the runtime" in output.out
    assert "entry\n" * 1000 in output.out
    assert _emit(payload, True) == 1
    assert json.loads(capsys.readouterr().out) == payload


def test_refusal_retains_partial_state(capsys):
    denied = response(
        "items.create", {"written": True, "public_ref": "APP-7"}
    ).model_copy(
        update={
            "success": False,
            "error": FunctionError(
                code="publish_pending",
                message="The record is stored, publication failed.",
                recovery_hint="Inspect the stored record before publishing.",
            ),
        }
    )
    assert emit_response(denied, json_mode=False) == 1
    output = capsys.readouterr()
    assert "written: yes" in output.out
    assert "public ref: APP-7" in output.out
    assert "publish_pending" in output.err


def test_authored_teaching_measurement_uses_terminal_cells():
    from yoke_cli.transport.response_evidence import wrapped_lines

    assert wrapped_lines("界" * 80) == 2
    assert wrapped_lines("\x1b[31m" + "x" * 80 + "\x1b[0m") == 1
