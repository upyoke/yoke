"""Registered read and write for an item's durable merge receipt document.

The merge boundary runs on the machine holding the checkout, and a control
plane reached over https has no local database there. These handlers put the
receipt write and read on the server side of that boundary so a merge records
its bookkeeping identically on a local Postgres universe and a relayed one.

They are ``adapter_status='internal'`` merge glue rather than an agent CLI
surface, and claim-free for the same reason the done-transition finalize
writes are: the item claim and merge lock are enforced upstream by the merge
boundary itself, and a receipt that could be refused here would take crash
recovery down with it.
"""

from __future__ import annotations

from typing import Any, List, Mapping, Optional

from pydantic import BaseModel, Field, ValidationError

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)
from yoke_core.domain import item_merge_receipt_document as document


class MergeFailure(BaseModel):
    label: str = ""
    phase: str = ""
    reason: str = ""


class RecordMergeReceiptRequest(BaseModel):
    branch: str = Field(..., min_length=1)
    target: str = Field(..., min_length=1)
    commit_sha: str = ""
    merge_sha: str = ""
    touched_files: List[str] = Field(default_factory=list)
    check_runs: List[dict] = Field(default_factory=list)
    failure: Optional[MergeFailure] = None
    settled: bool = False


class RecordMergeReceiptResponse(BaseModel):
    item_id: int
    entry: dict


class GetMergeReceiptRequest(BaseModel):
    branch: str = Field(..., min_length=1)
    # Lane retirement knows the branch but not the target it landed on.
    target: str = ""


class GetMergeReceiptResponse(BaseModel):
    item_id: int
    found: bool
    entry: Optional[dict] = None


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _item_id(request: FunctionCallRequest) -> Optional[int]:
    if request.target.kind != "item" or request.target.item_id is None:
        return None
    return int(request.target.item_id)


def _connect_rw() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def handle_record_merge_receipt(request: FunctionCallRequest) -> HandlerOutcome:
    """Fold one merge's facts into the item's receipt document."""
    item_id = _item_id(request)
    if item_id is None:
        return _err(
            "target_invalid",
            "merge_receipt.record requires target.kind='item' and item_id",
        )
    try:
        body = RecordMergeReceiptRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _err("payload_invalid", f"merge receipt payload invalid: {exc}")

    failure: Optional[Mapping[str, Any]] = None
    if body.failure is not None:
        failure = document.build_failure(
            label=body.failure.label,
            phase=body.failure.phase,
            reason=body.failure.reason,
        )
    try:
        with _connect_rw() as conn:
            entry = document.record_entry(
                conn,
                item_id=item_id,
                branch=body.branch,
                target=body.target,
                commit_sha=body.commit_sha,
                merge_sha=body.merge_sha,
                touched_files=body.touched_files,
                check_runs=body.check_runs,
                failure=failure,
                settled=body.settled,
            )
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - surfaced as an advisory refusal
        return _err("merge_receipt_record_failed", str(exc))
    return HandlerOutcome(
        result_payload={"item_id": item_id, "entry": entry},
        primary_success=True,
    )


def handle_get_merge_receipt(request: FunctionCallRequest) -> HandlerOutcome:
    """The item's newest receipt entry for one branch."""
    item_id = _item_id(request)
    if item_id is None:
        return _err(
            "target_invalid",
            "merge_receipt.get requires target.kind='item' and item_id",
        )
    try:
        body = GetMergeReceiptRequest.model_validate(request.payload or {})
    except ValidationError as exc:
        return _err("payload_invalid", f"merge receipt query invalid: {exc}")
    try:
        with _connect_rw() as conn:
            entry = document.find_entry(
                conn, item_id, branch=body.branch, target=body.target,
            )
    except Exception as exc:  # noqa: BLE001 - surfaced as an advisory refusal
        return _err("merge_receipt_read_failed", str(exc))
    return HandlerOutcome(
        result_payload={
            "item_id": item_id,
            "found": entry is not None,
            "entry": entry,
        },
        primary_success=True,
    )


__all__ = [
    "GetMergeReceiptRequest",
    "GetMergeReceiptResponse",
    "MergeFailure",
    "RecordMergeReceiptRequest",
    "RecordMergeReceiptResponse",
    "handle_get_merge_receipt",
    "handle_record_merge_receipt",
]
