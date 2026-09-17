"""Only a known-redundant receipt field condenses; every answer prints whole."""

from __future__ import annotations

import json

from yoke_cli.transport import public_ref_display
from yoke_cli.transport.receipt_compaction import (
    CONDENSE_ABOVE_BYTES,
    REDUNDANT_RECEIPT_FIELDS,
    compact_receipt,
    omission_advisory,
)
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)

#: Wording that would send a reader back to run the command again. A receipt
#: prints after the command has already run, so for a mutation any of these
#: is an instruction to redo the write in order to read its output.
REPLAY_PHRASES = (
    "rerun",
    "re-run",
    "run it again",
    "run again",
    "repeat the command",
    "repeating this command",
    "retry the command",
    "run the command again",
    "execute it again",
)


def _session_row() -> dict:
    """The stored row `sessions.touch` hands back to confirm one field."""
    return {f"column_{index}": "x" * 40 for index in range(100)}


def _response(function: str, result: dict) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True, function=function, version="v1", result=result
    )


def test_a_large_requested_read_prints_complete():
    """A read's value is the answer that was asked for, at any size."""
    body = "## Spec\n" + ("a paragraph of the requested body. " * 300)
    receipt = {"item_id": 51, "fields": {"body": body}}
    assert len(json.dumps(receipt)) > 2000

    display, condensed = compact_receipt("items.get.run", receipt)

    assert display == receipt
    assert condensed == []
    assert display["fields"]["body"] == body


def test_runnable_commands_a_result_emits_are_never_condensed():
    """A result that hands the caller commands to run must keep them."""
    index = {
        f"section_{n}": {
            "bytes": 4000,
            "read": f"yoke items get ACM-22 section_{n}",
        }
        for n in range(60)
    }
    receipt = {"item": {"content_index": index}}
    assert len(json.dumps(receipt)) > 2000

    display, condensed = compact_receipt("items.detail.get", receipt)

    assert display == receipt
    assert condensed == []


def test_mutation_bulk_alone_condenses():
    receipt = {"success": True, "session": _session_row()}

    display, condensed = compact_receipt("sessions.touch", receipt)

    assert condensed == ["session"]
    assert display["success"] is True
    assert display["session"].startswith("<not printed: ")
    assert f"{len(_session_row())} keys" in display["session"]


def test_an_unlisted_mutation_is_left_alone():
    """Missing an entry leaves a receipt long, never an answer missing."""
    receipt = {"success": True, "session": _session_row()}
    assert "sessions.checkpoint" not in REDUNDANT_RECEIPT_FIELDS

    display, condensed = compact_receipt("sessions.checkpoint", receipt)

    assert display == receipt
    assert condensed == []


def test_unlisted_fields_of_a_listed_function_survive():
    receipt = {"success": True, "session": _session_row(), "offer": _session_row()}

    display, condensed = compact_receipt("sessions.touch", receipt)

    assert condensed == ["session"]
    assert display["offer"] == _session_row()


def test_a_small_listed_field_is_not_worth_a_marker():
    receipt = {"success": True, "session": {"mode": "parked"}}
    assert len(json.dumps(receipt["session"])) <= CONDENSE_ABOVE_BYTES

    display, condensed = compact_receipt("sessions.touch", receipt)

    assert display == receipt
    assert condensed == []


def test_every_listed_field_names_a_mutation_not_a_read():
    """A read's content must never be reachable by this path."""
    for function in REDUNDANT_RECEIPT_FIELDS:
        tail = function.rsplit(".", 1)[-1]
        assert tail not in {"get", "list", "read", "run"}, function


def test_no_printed_wording_tells_the_reader_to_run_the_command_again():
    display, condensed = compact_receipt(
        "sessions.touch", {"success": True, "session": _session_row()}
    )
    printed = f"{json.dumps(display)} {omission_advisory(condensed)}".lower()

    for phrase in REPLAY_PHRASES:
        assert phrase not in printed, phrase
    assert "--json" in printed
    assert "already run" in printed


def test_json_mode_prints_the_whole_envelope(capsys):
    receipt = {"success": True, "session": _session_row()}

    public_ref_display.emit_response(
        _response("sessions.touch", receipt), json_mode=True
    )

    captured = capsys.readouterr()
    assert json.loads(captured.out)["result"] == receipt
    assert captured.err == ""


def test_human_mode_names_the_condensed_field_on_stderr(capsys):
    public_ref_display.emit_response(
        _response("sessions.touch", {"success": True, "session": _session_row()}),
        json_mode=False,
    )

    captured = capsys.readouterr()
    assert json.loads(captured.out)["session"].startswith("<not printed: ")
    assert "receipt: session" in captured.err
    for phrase in REPLAY_PHRASES:
        assert phrase not in captured.err.lower(), phrase


def test_a_refusal_keeps_its_named_reason_and_recovery(capsys):
    refusal = FunctionCallResponse(
        success=False,
        function="sessions.touch",
        version="v1",
        error=FunctionError(
            code="session_required",
            message="session id is required",
            recovery_hint="yoke sessions begin --session-id ...",
        ),
    )

    public_ref_display.emit_response(refusal, json_mode=False)

    captured = capsys.readouterr()
    assert "session_required" in captured.err
    assert "session id is required" in captured.err
    assert "yoke sessions begin --session-id ..." in captured.err
