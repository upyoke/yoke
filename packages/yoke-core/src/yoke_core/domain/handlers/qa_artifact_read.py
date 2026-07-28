"""Authorized QA artifact evidence reads for local and S3 handles."""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.qa import _error, _p

READ_EXPIRES_S = 300
MAX_INLINE_BYTES = 20 * 1024 * 1024


class QaArtifactReadRequest(BaseModel):
    artifact_id: int


class QaArtifactReadResponse(BaseModel):
    artifact_id: int
    backend: str
    disposition: str
    content_type: Optional[str] = None
    download_url: Optional[str] = None
    content_base64: Optional[str] = None
    machine: Optional[str] = None
    detail: Optional[str] = None
    expires_in_s: Optional[int] = None


def _inside(path: Path, roots: list[Path]) -> bool:
    candidate = path.resolve(strict=False)
    return any(
        candidate == root.resolve(strict=False)
        or root.resolve(strict=False) in candidate.parents
        for root in roots
    )


def _machine_label(raw: object) -> Optional[str]:
    try:
        metadata = raw if isinstance(raw, dict) else json.loads(str(raw or "{}"))
    except (TypeError, ValueError):
        return None
    for key in ("machine", "machine_name", "host", "host_baseline"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _local_result(row, handle: dict) -> dict:
    from yoke_core.domain.project_checkout_locations import (
        checkout_for_project_id,
    )
    from yoke_core.domain.qa_artifacts import (
        artifact_directory,
        case_artifact_subject,
    )

    checkout = checkout_for_project_id(int(row["project_id"]))
    scratch = artifact_directory(
        str(row["project"]),
        case_artifact_subject(dict(row)),
        int(row["run_id"]),
        create=False,
    )
    roots = [scratch]
    if checkout is not None:
        roots.append(checkout)
    raw_path = Path(str(handle["path"])).expanduser()
    path = (
        raw_path
        if raw_path.is_absolute()
        else (checkout / raw_path if checkout is not None else raw_path)
    )
    machine = _machine_label(row["metadata"])
    if not path.is_absolute() or not _inside(path, roots):
        return {
            "disposition": "evidence_on_machine",
            "machine": machine,
            "detail": "the local handle is outside this server's evidence roots",
        }
    if not path.is_file():
        return {
            "disposition": (
                "evidence_on_machine" if machine else "evidence_not_portable"
            ),
            "machine": machine,
            "detail": "the evidence bytes are not present on this machine",
        }
    size = path.stat().st_size
    if size > MAX_INLINE_BYTES:
        return {
            "disposition": "too_large",
            "detail": f"local evidence is {size} bytes; inline limit is {MAX_INLINE_BYTES}",
        }
    return {
        "disposition": "ready",
        "content_base64": base64.b64encode(path.read_bytes()).decode("ascii"),
    }


def _s3_result(conn, row, handle: dict) -> tuple[dict, Optional[HandlerOutcome]]:
    from yoke_core.domain.handlers.qa_artifact_presign import (
        _aws_region,
        _capability_credentials,
        resolve_artifacts_bucket,
    )
    from yoke_core.domain.s3_presign import presign_s3_url

    configured = resolve_artifacts_bucket(
        conn,
        int(row["project_id"]),
        row["target_env"],
    )
    if configured is None or configured[1] != str(handle["bucket"]):
        return {
            "disposition": "evidence_not_portable",
            "detail": "the recorded object belongs to a different artifact store",
        }, None
    region = _aws_region(conn, int(row["project_id"]))
    credentials = _capability_credentials(str(row["project"]))
    if not region or credentials is None:
        return {}, _error(
            "s3_not_configured",
            "the project artifact store cannot mint a download URL",
        )
    return {
        "disposition": "ready",
        "download_url": presign_s3_url(
            method="GET",
            bucket=str(handle["bucket"]),
            key=str(handle["key"]),
            region=region,
            credentials=credentials,
            expires_s=READ_EXPIRES_S,
        ),
        "expires_in_s": READ_EXPIRES_S,
    }, None


def handle_qa_artifact_read(
    request: FunctionCallRequest,
) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, query_one
    from yoke_core.domain.qa_artifact_handle import ArtifactHandleError, parse_handle

    req_id = request.target.qa_requirement_id
    if req_id is None:
        return _error(
            "target_invalid",
            "qa.artifact.read requires target.qa_requirement_id",
        )
    try:
        payload = QaArtifactReadRequest.model_validate(request.payload or {})
    except ValueError as exc:
        return _error("payload_invalid", str(exc), jsonpath="$.payload")
    with connect() as conn:
        marker = _p(conn)
        row = query_one(
            conn,
            "SELECT a.id, a.content_type, a.artifact_handle, a.metadata, "
            "a.qa_run_id AS run_id, r.qa_requirement_id, q.item_id, "
            "q.deployment_run_id, q.target_env, "
            "COALESCE(i.project_id, d.project_id) AS project_id, "
            "p.slug AS project "
            "FROM qa_artifacts a JOIN qa_runs r ON r.id=a.qa_run_id "
            "JOIN qa_requirements q ON q.id=r.qa_requirement_id "
            "LEFT JOIN items i ON i.id=q.item_id "
            "LEFT JOIN deployment_runs d ON d.id=q.deployment_run_id "
            "JOIN projects p ON p.id=COALESCE(i.project_id, d.project_id) "
            f"WHERE a.id={marker}",
            (payload.artifact_id,),
        )
        if row is None:
            return _error("not_found", f"artifact {payload.artifact_id} not found")
        if int(row["qa_requirement_id"]) != int(req_id):
            return _error(
                "target_invalid",
                f"artifact {payload.artifact_id} does not belong to "
                f"requirement {req_id}",
            )
        try:
            handle = parse_handle(row["artifact_handle"])
        except ArtifactHandleError as exc:
            return _error("artifact_malformed", str(exc))
        if handle["backend"] == "s3":
            result, error = _s3_result(conn, row, handle)
            if error is not None:
                return error
        else:
            result = _local_result(row, handle)
    return HandlerOutcome(
        result_payload={
            "artifact_id": payload.artifact_id,
            "backend": handle["backend"],
            "content_type": row["content_type"] or handle.get("content_type"),
            **result,
        },
        primary_success=True,
    )


__all__ = [
    "QaArtifactReadRequest",
    "QaArtifactReadResponse",
    "handle_qa_artifact_read",
]
