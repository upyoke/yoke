"""A printed receipt keeps its actionable facts and names what it drops."""

from __future__ import annotations

import json

from yoke_cli.transport import public_ref_display
from yoke_cli.transport.receipt_compaction import (
    COMPACTABLE_VALUE_BYTES,
    RECEIPT_BYTE_CAP,
    compact_receipt,
)
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)


def _oversized_row() -> dict:
    """A stored row of the shape a one-field stamp hands back in full."""
    return {f"field_{index}": "x" * 40 for index in range(RECEIPT_BYTE_CAP // 20)}


def _response(result: dict) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True, function="sessions.touch", version="v1", result=result
    )


def test_an_ordinary_receipt_prints_exactly_as_returned():
    receipt = {"public_ref": "ACM-22", "to_status": "done", "changed": True}

    display, omitted = compact_receipt(receipt)

    assert display == receipt
    assert omitted == []


def test_a_bulky_value_is_replaced_and_its_small_siblings_survive():
    receipt = {"success": True, "public_ref": "ACM-22", "session": _oversized_row()}

    display, omitted = compact_receipt(receipt)

    assert omitted == ["session"]
    assert display["success"] is True
    assert display["public_ref"] == "ACM-22"
    assert display["session"].startswith("<omitted: ")
    assert "rerun with --json" in display["session"]
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

    display, omitted = compact_receipt(receipt)

    assert display == receipt
    assert omitted == []


def test_json_mode_prints_the_whole_envelope_regardless_of_size(capsys):
    receipt = {"success": True, "session": _oversized_row()}

    public_ref_display.emit_response(_response(receipt), json_mode=True)

    captured = capsys.readouterr()
    assert json.loads(captured.out)["result"] == receipt
    assert "omitted" not in captured.err


def test_human_mode_names_the_omission_on_stderr(capsys):
    public_ref_display.emit_response(
        _response({"success": True, "session": _oversized_row()}), json_mode=False
    )

    captured = capsys.readouterr()
    assert json.loads(captured.out)["session"].startswith("<omitted: ")
    assert "receipt: omitted session" in captured.err
    assert "rerun with --json" in captured.err


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
