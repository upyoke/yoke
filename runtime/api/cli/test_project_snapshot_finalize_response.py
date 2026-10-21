"""Finalize outlives hook staging and must not abort ambiguous server work."""

from unittest.mock import patch

import pytest

from yoke_cli.commands.adapters import project_snapshot_chunked as chunks
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError
from yoke_contracts.path_snapshot_chunks import PathSnapshotChunkSyncPayload


@pytest.mark.parametrize("operation,expected", [("append", 8.0), ("finalize", 60.0)])
def test_response_budget_covers_finalize(operation, expected):
    payload = PathSnapshotChunkSyncPayload(
        upload_id="upload", operation=operation,
        **({"chunk_index": 0, "files": [{"path": "README.md", "line_count": 1}]} if operation == "append" else {}),
    )
    with (
        patch.object(chunks, "raise_if_https_chunk_payload_too_large"),
        patch.object(chunks, "ensure_handlers_loaded"),
        patch.object(chunks, "build_actor"),
        patch.object(chunks, "call_dispatcher") as dispatch,
    ):
        chunks.dispatch_chunk_payload(
            project="demo", payload=payload, session_id=None, timeout_s=8.0
        )
    assert dispatch.call_args.kwargs["timeout_s"] == expected


@pytest.mark.parametrize("operation", ["append", "finalize"])
@pytest.mark.parametrize("raises", [False, True])
def test_lost_finalize_response_does_not_abort_server_work(operation, raises):
    payload = PathSnapshotChunkSyncPayload(
        upload_id="upload", operation=operation,
        **({"chunk_index": 0, "files": [{"path": "README.md", "line_count": 1}]} if operation == "append" else {}),
    )
    lost_response = FunctionCallResponse(
        success=False, function="project.snapshot.sync", version="v1",
        error=FunctionError(code="https_response_timeout", message="response lost"),
    )
    with (
        patch.object(chunks, "dispatch_chunk_payload", return_value=lost_response,
                     side_effect=TimeoutError("response lost") if raises else None),
        patch.object(chunks, "abort_chunk_upload") as abort,
    ):
        if raises:
            with pytest.raises(TimeoutError):
                chunks._dispatch_or_abort("demo", "upload", payload, None, 8.0)
        else:
            assert chunks._dispatch_or_abort(
                "demo", "upload", payload, None, 8.0
            ) == lost_response
    assert abort.call_count == (0 if operation == "finalize" else 1)
