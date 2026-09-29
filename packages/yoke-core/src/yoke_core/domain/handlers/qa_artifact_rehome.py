"""``qa.artifact.rehome`` — move recorded local evidence into the serving store.

A capture recorded through a database door into a hosted universe carries a
local handle naming the capture machine's disk, which no hosted reviewer can
open. The capture machine still holds those bytes. This takes them, stores
them exactly as a fresh capture would be stored by the build serving the
universe, and swaps the recorded handle on the SAME artifact row — so the
run, its verdict, and every review request that shows the artifact keep
their identity, and no second copy of the evidence appears beside the first.
The handle it replaced is kept in the artifact's metadata as provenance.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from pathlib import Path
from typing import Any, Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.qa import _error, _p


class QaArtifactRehomeRequest(BaseModel):
    artifact_id: int
    content_base64: str


class QaArtifactRehomeResponse(BaseModel):
    artifact_id: int
    rehomed: bool
    artifact_handle: dict[str, Any]
    previous_handle: Optional[dict[str, Any]] = None
    sha256: Optional[str] = None


def _metadata(raw: object) -> dict[str, Any]:
    try:
        value = raw if isinstance(raw, dict) else json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def handle_qa_artifact_rehome(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, iso8601_now, query_one
    from yoke_core.domain.qa_artifact_handle import (
        ArtifactHandleError,
        parse_handle,
        serialize_handle,
    )
    from yoke_core.domain.qa_artifact_storage import (
        ArtifactStorageError,
        store_artifact_bytes,
    )

    req_id = request.target.qa_requirement_id
    if req_id is None:
        return _error(
            "target_invalid", "qa.artifact.rehome requires target.qa_requirement_id"
        )
    try:
        payload = QaArtifactRehomeRequest.model_validate(request.payload or {})
        content = base64.b64decode(payload.content_base64, validate=True)
    except (binascii.Error, ValueError) as exc:
        return _error("payload_invalid", str(exc), jsonpath="$.payload")
    with connect() as conn:
        marker = _p(conn)
        row = query_one(
            conn,
            "SELECT a.id, a.qa_run_id, a.content_type, a.artifact_handle, "
            "a.metadata, r.qa_requirement_id FROM qa_artifacts a "
            f"JOIN qa_runs r ON r.id=a.qa_run_id WHERE a.id={marker}",
            (payload.artifact_id,),
        )
        if row is None:
            return _error("not_found", f"artifact {payload.artifact_id} not found")
        if int(row["qa_requirement_id"]) != int(req_id):
            return _error(
                "target_invalid",
                f"artifact {payload.artifact_id} does not belong to "
                f"requirement {req_id}; name the requirement whose run "
                "captured it",
            )
        try:
            previous = parse_handle(row["artifact_handle"])
        except ArtifactHandleError as exc:
            return _error("artifact_malformed", str(exc))
        if previous["backend"] != "local":
            # Already in an object store: nothing to move, and repeating the
            # recovery after a partial batch must not fail the rest.
            return HandlerOutcome(
                result_payload={
                    "artifact_id": payload.artifact_id,
                    "rehomed": False,
                    "artifact_handle": previous,
                },
                primary_success=True,
            )
        content_type = row["content_type"] or previous.get("content_type")
        try:
            stored = store_artifact_bytes(
                conn,
                requirement_id=int(req_id),
                run_id=int(row["qa_run_id"]),
                filename=Path(str(previous["path"])).name,
                content=content,
                content_type=content_type,
            )
        except ArtifactStorageError as exc:
            return _error(exc.code, str(exc))
        except ValueError as exc:
            return _error("payload_invalid", str(exc), jsonpath="$.payload")
        digest = hashlib.sha256(content).hexdigest()
        metadata = _metadata(row["metadata"])
        metadata["rehomed_from"] = {
            "artifact_handle": previous,
            "sha256": digest,
            "at": iso8601_now(),
        }
        # Compare-and-set on the handle this call read, so two recoveries
        # racing on one artifact cannot both claim to have moved it.
        cursor = conn.execute(
            f"UPDATE qa_artifacts SET artifact_handle={marker}, metadata={marker} "
            f"WHERE id={marker} AND artifact_handle={marker}",
            (
                serialize_handle(stored),
                json.dumps(metadata, sort_keys=True),
                payload.artifact_id,
                row["artifact_handle"],
            ),
        )
        if cursor.rowcount != 1:
            conn.rollback()
            return _error(
                "artifact_changed",
                f"artifact {payload.artifact_id} changed while it was being "
                "moved; read it again and re-run the recovery if it is still local",
            )
        conn.commit()
    return HandlerOutcome(
        result_payload={
            "artifact_id": payload.artifact_id,
            "rehomed": True,
            "artifact_handle": stored,
            "previous_handle": previous,
            "sha256": digest,
        },
        primary_success=True,
    )


__all__ = [
    "QaArtifactRehomeRequest",
    "QaArtifactRehomeResponse",
    "handle_qa_artifact_rehome",
]
