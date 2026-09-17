"""A printed receipt keeps its actionable facts and never advises a repeat."""

from __future__ import annotations

import json

from yoke_cli.transport import public_ref_display
from yoke_cli.transport.receipt_compaction import (
    ACTIONABLE_KEYS,
    COMPACTABLE_VALUE_BYTES,
    RECEIPT_BYTE_CAP,
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


def _oversized_row() -> dict:
    """A stored row of the shape a one-field stamp hands back in full."""
    return {f"field_{index}": "x" * 40 for index in range(RECEIPT_BYTE_CAP // 20)}


def _oversized_blockers() -> list:
    """A long list of real blockers — bulky, and every entry actionable."""
    return [
        {"path": f"packages/thing_{index}.py", "owner_public_ref": "ACM-9"}
        for index in range(RECEIPT_BYTE_CAP // 40)
    ]


def _response(result: dict) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True, function="sessions.touch", version="v1", result=result
    )


def test_an_ordinary_receipt_prints_exactly_as_returned():
    receipt = {"public_ref": "ACM-22", "to_status": "done", "changed": True}

    display, marked = compact_receipt(receipt)

    assert display == receipt
    assert marked == []


def test_a_bulky_value_is_marked_and_its_small_siblings_survive():
    receipt = {"success": True, "public_ref": "ACM-22", "session": _oversized_row()}

    display, marked = compact_receipt(receipt)

    assert marked == ["session"]
    assert display["success"] is True
    assert display["public_ref"] == "ACM-22"
    assert display["session"].startswith("<not printed: ")
    assert f"{len(_oversized_row())} keys" in display["session"]
    assert len(json.dumps(display)) < RECEIPT_BYTE_CAP


def test_a_receipt_made_only_of_small_facts_is_left_whole():
    """Shortening these would remove the answer rather than its bulk."""
    receipt = {f"fact_{index}": index for index in range(RECEIPT_BYTE_CAP // 10)}
    assert len(json.dumps(receipt)) > RECEIPT_BYTE_CAP
    assert all(
        len(json.dumps(value)) < COMPACTABLE_VALUE_BYTES
        for value in receipt.values()
    )

    display, marked = compact_receipt(receipt)

    assert display == receipt
    assert marked == []


def test_size_alone_never_removes_an_actionable_fact():
    """A long list of blockers is why the reader is reading."""
    blockers = _oversized_blockers()
    receipt = {"clear": False, "blockers": blockers, "session": _oversized_row()}
    assert len(json.dumps(blockers)) >= COMPACTABLE_VALUE_BYTES

    display, marked = compact_receipt(receipt)

    assert display["blockers"] == blockers
    assert marked == ["session"]


def test_an_actionable_fact_nested_in_bulk_keeps_its_container():
    """Nesting must not defeat the rule that failures always print."""
    carrier = dict(_oversized_row(), warnings=["the lane is behind its base"])
    receipt = {"lane_sweep": carrier, "session": _oversized_row()}

    display, marked = compact_receipt(receipt)

    assert display["lane_sweep"] == carrier
    assert marked == ["session"]


def test_an_empty_actionable_key_does_not_pin_bulk():
    """`warnings: []` reports nothing to act on, so it holds nothing open."""
    carrier = dict(_oversized_row(), warnings=[])
    receipt = {"lane_sweep": carrier, "success": True}

    _display, marked = compact_receipt(receipt)

    assert marked == ["lane_sweep"]


def test_every_actionable_key_survives_at_any_size():
    receipt = {
        key: {f"detail_{index}": "y" * 40 for index in range(40)}
        for key in ACTIONABLE_KEYS
    }
    assert len(json.dumps(receipt)) > RECEIPT_BYTE_CAP

    display, marked = compact_receipt(receipt)

    assert marked == []
    assert display == receipt


def test_no_printed_wording_tells_the_reader_to_run_the_command_again():
    """A mutation receipt must never advise replaying the write."""
    display, marked = compact_receipt(
        {"success": True, "session": _oversized_row()}
    )
    printed = f"{json.dumps(display)} {omission_advisory(marked)}".lower()

    for phrase in REPLAY_PHRASES:
        assert phrase not in printed, phrase
    assert "--json" in printed
    assert "already run" in printed


def test_json_mode_prints_the_whole_envelope_regardless_of_size(capsys):
    receipt = {"success": True, "session": _oversized_row()}

    public_ref_display.emit_response(_response(receipt), json_mode=True)

    captured = capsys.readouterr()
    assert json.loads(captured.out)["result"] == receipt
    assert captured.err == ""


def test_human_mode_names_the_marked_key_on_stderr(capsys):
    public_ref_display.emit_response(
        _response({"success": True, "session": _oversized_row()}), json_mode=False
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
