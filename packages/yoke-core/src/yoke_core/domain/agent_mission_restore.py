"""Validate durable mission walk-end receipts independently of cancellation time."""

import base64
import binascii
import json
from typing import Any

from yoke_core.domain.db_helpers import query_one


def mission_restores_proven(conn: Any, execution: dict) -> bool:
    """Every mission proves its declared starting state was restored."""
    from yoke_core.domain.qa_plan_execution_abort_state import host_cleanup_proven

    ordinals = [
        ordinal
        for ordinal, case in enumerate(execution.get("roster") or [])
        if case.get("runner_id") == "agent_mission"
    ]
    return bool(ordinals) and all(
        host_cleanup_proven(conn, execution, ordinal) for ordinal in ordinals
    )


def recorded_mission_restore(
    conn: Any, *, requirement_id: int, run_id: int
) -> dict | None:
    """Read the latest receipt through the artifact reader's ownership checks.

    Missing, malformed or unreadable bytes prove nothing: custody remains
    held for walk-end recovery. This reads the actual local/S3 payload,
    rather than trusting the artifact type or caller-supplied metadata.
    """
    from yoke_core.domain.handlers.qa_artifact_read import _local_result, _s3_result
    from yoke_core.domain.qa_artifact_handle import ArtifactHandleError, parse_handle
    from yoke_core.domain.qa_artifact_owner import requirement_storage_owner
    from yoke_core.domain.qa_artifact_text_inline import inline_text_base64

    artifact = query_one(
        conn,
        "SELECT artifact_handle,metadata FROM qa_artifacts WHERE qa_run_id=%s "
        "AND artifact_type='starting_state_restore' ORDER BY created_at DESC,id DESC LIMIT 1",
        (run_id,),
    )
    if artifact is None:
        return None
    try:
        row = {**requirement_storage_owner(conn, requirement_id), **artifact, "run_id": run_id}
        handle = parse_handle(artifact["artifact_handle"])
        if handle["backend"] == "s3":
            result, error = _s3_result(conn, row, handle)
            if error is not None or not result.get("download_url"):
                return None
            content = inline_text_base64(result["download_url"])
        else:
            content = _local_result(row, handle).get("content_base64")
        if content is None:
            return None
        receipt = json.loads(base64.b64decode(content, validate=True))
    except (ArtifactHandleError, OSError, ValueError, LookupError, binascii.Error):
        return None
    return receipt if isinstance(receipt, dict) else None
