"""Read back the merge-group receipt a landing already recorded.

The twin of :mod:`yoke_core.domain.handlers.merge_engine_post_rebase_ci`,
which writes that receipt. Close-out runs more than once for a member that
parks at a release wait — once when its train lands, and again at the
deployment wake — and only the first of those runs while the Actions window
still reaches the train. The second one reads this instead.

Claim-free and transport-aware for the same reason the write is: the merge
engine holds a merge lock rather than an item claim, and an https control
plane has no local connection for the caller to open.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import (
    FunctionCallRequest,
    FunctionError,
    HandlerOutcome,
)


class RecordedQueueReceiptRequest(BaseModel):
    """Which landing the caller is asking about."""

    pr_num: str = ""


class RecordedQueueReceiptResponse(BaseModel):
    """The recorded block, or an explicit absence."""

    found: bool
    pr_num: str = ""
    merge_sha: str = ""
    combined_head_sha: str = ""
    run_url: str = ""
    members: list[str] = []
    drift_check: dict[str, str] = {}


def _err(code: str, message: str) -> HandlerOutcome:
    return HandlerOutcome(
        primary_success=False,
        error=FunctionError(code=code, message=message),
    )


def _connect() -> Any:
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def _matching_block(
    blocks: tuple[dict[str, Any], ...],
    pr_num: str,
) -> Optional[dict[str, Any]]:
    """The newest recorded block answering for ``pr_num``.

    A pull request merges once, so its number identifies one landing
    exactly. Matching on it is what keeps a receipt from an item's earlier
    landing — a correction that re-merged — from being read as proof of the
    landing being closed out now.

    A block missing either the combined head or the run URL is not a
    receipt: those two are what the terminal gate compares against, and
    answering with half of one would replace a stale-window failure with a
    silently incomplete pass.
    """
    wanted = str(pr_num or "").strip()
    for block in blocks:
        if wanted and str(block.get("pr_num") or "").strip() != wanted:
            continue
        if not str(block.get("combined_head_sha") or "").strip():
            continue
        if not str(block.get("run_url") or "").strip():
            continue
        return block
    return None


def handle_recorded_queue_receipt(request: FunctionCallRequest) -> HandlerOutcome:
    """Return the merge-group receipt already recorded for this item."""
    item_id = request.target.item_id
    if item_id is None:
        return _err(
            "target_invalid",
            "recorded_queue_receipt requires target.item_id",
        )
    try:
        body = RecordedQueueReceiptRequest.model_validate(request.payload or {})
    except Exception as exc:  # noqa: BLE001 - structured payload error
        return _err(
            "payload_invalid",
            f"recorded queue receipt payload invalid: {exc}",
        )

    from yoke_core.domain.qa_merging_identity import recorded_batch_blocks

    try:
        conn = _connect()
        try:
            blocks = recorded_batch_blocks(conn, int(item_id))
        finally:
            conn.close()
    except Exception as exc:  # noqa: BLE001 - merge must see a structured failure
        return _err("recorded_queue_receipt_read_failed", str(exc))

    block = _matching_block(blocks, body.pr_num)
    if block is None:
        return HandlerOutcome(
            result_payload={"found": False},
            primary_success=True,
        )
    drift = block.get("drift_check")
    return HandlerOutcome(
        result_payload={
            "found": True,
            "pr_num": str(block.get("pr_num") or ""),
            "merge_sha": str(block.get("merge_sha") or ""),
            "combined_head_sha": str(block.get("combined_head_sha") or ""),
            "run_url": str(block.get("run_url") or ""),
            "members": [
                str(member) for member in (block.get("members") or [])
            ],
            "drift_check": {
                str(key): str(value)
                for key, value in (drift or {}).items()
            } if isinstance(drift, dict) else {},
        },
        primary_success=True,
    )


__all__ = [
    "RecordedQueueReceiptRequest",
    "RecordedQueueReceiptResponse",
    "handle_recorded_queue_receipt",
]
