"""``qa.artifact.add`` — record a typed handle or store inline evidence bytes."""

from __future__ import annotations

import base64
import binascii
from typing import Any, Optional

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.handlers.qa import _error, _p
from yoke_core.domain.handlers.qa_browser_write_models import (
    QaArtifactAddRequest,
    QaArtifactAddResponse,
)

_EXCLUSIVE_GUIDANCE = "pass artifact_handle or content_base64 plus filename, not both"


class ArtifactOwnerError(ValueError):
    """The requirement has no item or deployment-run project owner."""


def _decode_inline_bytes(raw: object, filename: object) -> tuple[bytes, str]:
    from yoke_core.domain.handlers.qa_artifact_read import MAX_INLINE_BYTES
    from yoke_core.domain.qa_artifact_handle import safe_segment

    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("content_base64 is required")
    if not isinstance(filename, str) or not filename.strip():
        raise ValueError("filename is required with content_base64")
    try:
        content = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"content_base64 is not valid base64: {exc}") from exc
    if not content:
        raise ValueError("content_base64 decoded to empty bytes")
    if len(content) > MAX_INLINE_BYTES:
        raise ValueError(
            f"inline content is {len(content)} bytes; limit is {MAX_INLINE_BYTES}"
        )
    return content, safe_segment(filename)


def _requirement_owner(conn, req_id: int) -> dict[str, Any]:
    """Return the requirement's project-owning row for artifact storage."""
    from yoke_core.domain.db_helpers import query_one

    p = _p(conn)
    req_row = query_one(
        conn,
        "SELECT r.item_id, r.epic_id, r.task_num, r.deployment_run_id, "
        "COALESCE(i.project_id, d.project_id) AS project_id, "
        "p.slug AS project "
        "FROM qa_requirements r "
        "LEFT JOIN items i ON i.id = r.item_id "
        "LEFT JOIN deployment_runs d ON d.id = r.deployment_run_id "
        "LEFT JOIN projects p "
        "ON p.id = COALESCE(i.project_id, d.project_id) "
        f"WHERE r.id = {p}",
        (int(req_id),),
    )
    if req_row is None:
        raise LookupError(f"requirement {req_id} not found")
    if req_row["project"] is None:
        raise ArtifactOwnerError(
            f"requirement {req_id} resolves to no project through its "
            f"owner (item_id={req_row['item_id']!r}, "
            f"epic_id={req_row['epic_id']!r}, "
            f"deployment_run_id={req_row['deployment_run_id']!r}); "
            "inline evidence stores under an item-owned or "
            "deployment-run-owned requirement"
        )
    return dict(req_row)


def _mission_handle_refusal(
    conn,
    *,
    req_id: int,
    run_id: int,
    handle: dict[str, Any],
) -> Optional[str]:
    """Name why a mission capture's local handle is not readable evidence.

    An ``agent_mission`` walk runs on a QA test host whose home is reset
    between missions, so a handle naming that host outlives its own bytes:
    the artifact row survives the reset and the file does not. Accept such a
    handle only where this control plane can address the path itself AND the
    bytes are there — the location says the transfer had somewhere to land,
    presence says it actually did — which is exactly what the evidence reader
    will later require of the same row.
    """
    from yoke_core.domain.db_helpers import query_one
    from yoke_core.domain.project_checkout_locations import (
        checkout_for_project_id,
    )
    from yoke_core.domain.qa_artifact_handle import is_present
    from yoke_core.domain.qa_artifacts import (
        case_artifact_subject,
        is_server_evidence_path,
    )

    if handle.get("backend") != "local":
        return None
    run_row = query_one(
        conn,
        f"SELECT performed_by FROM qa_runs WHERE id = {_p(conn)}",
        (int(run_id),),
    )
    if run_row is None or str(run_row["performed_by"]) != "agent_mission":
        return None
    req_row = _requirement_owner(conn, int(req_id))
    recipe = (
        "Send the bytes instead so they persist in project artifact storage: "
        f"yoke qa artifact add --requirement-id {int(req_id)} --run-id "
        f"{int(run_id)} --artifact-type TYPE --content-file PATH"
    )
    if not is_server_evidence_path(
        str(handle["path"]),
        str(req_row["project"]),
        case_artifact_subject(req_row),
        int(run_id),
        checkout=checkout_for_project_id(int(req_row["project_id"])),
    ):
        return (
            f"artifact_handle names {handle['path']!r}, which this control "
            "plane cannot read. A mission capture lives on the QA test host, "
            "whose home is reset between missions, so recording the handle "
            f"would outlive its own bytes. {recipe}"
        )
    if not is_present(handle):
        return (
            f"artifact_handle names {handle['path']!r}, which is inside this "
            "control plane's evidence storage but holds no bytes: a transfer "
            "that never arrived would be recorded as readable evidence. "
            f"{recipe}"
        )
    return None


def _store_inline_bytes(
    conn,
    *,
    req_id: int,
    run_id: int,
    content: bytes,
    filename: str,
    content_type: Optional[str],
) -> str:
    from yoke_core.domain.qa_artifact_handle import local_handle, serialize_handle
    from yoke_core.domain.qa_artifacts import (
        artifact_file_path,
        case_artifact_subject,
    )

    req_row = _requirement_owner(conn, int(req_id))
    subject = case_artifact_subject(req_row)
    path = artifact_file_path(
        str(req_row["project"]),
        subject,
        int(run_id),
        filename,
    )
    path.write_bytes(content)
    return serialize_handle(
        local_handle(str(path), content_type=content_type),
    )


def _present(payload: dict[str, Any], key: str) -> bool:
    return key in payload and payload.get(key) not in (None, "")


def handle_qa_artifact_add(request: FunctionCallRequest) -> HandlerOutcome:
    from yoke_core.domain.db_helpers import connect, iso8601_now
    from yoke_core.domain.qa_artifact_handle import (
        ArtifactHandleError,
        parse_handle,
        serialize_handle,
    )
    from yoke_core.domain.qa_artifact_ops import (
        BARE_PATH_GUIDANCE,
        QaArtifactLimitError,
        ensure_artifact_capacity,
    )

    req_id = request.target.qa_requirement_id
    if req_id is None:
        return _error(
            "target_invalid",
            "qa.artifact.add requires target.qa_requirement_id",
        )
    payload = request.payload or {}
    run_id = payload.get("run_id")
    artifact_type = payload.get("artifact_type")
    content_type = payload.get("content_type")
    metadata = payload.get("metadata")
    if not isinstance(run_id, int):
        return _error(
            "payload_invalid",
            "run_id is required",
            jsonpath="$.payload.run_id",
        )
    if not isinstance(artifact_type, str) or not artifact_type:
        return _error(
            "payload_invalid",
            "artifact_type is required",
            jsonpath="$.payload.artifact_type",
        )
    if "storage_path" in payload:
        return _error(
            "payload_invalid",
            f"storage_path is retired; {BARE_PATH_GUIDANCE}",
            jsonpath="$.payload.storage_path",
        )
    has_handle = _present(payload, "artifact_handle")
    has_inline = (
        "content_base64" in payload and payload.get("content_base64") is not None
    )
    if has_handle and has_inline:
        return _error(
            "payload_invalid",
            f"{_EXCLUSIVE_GUIDANCE}. {BARE_PATH_GUIDANCE}",
            jsonpath="$.payload.content_base64",
        )
    if not has_handle and not has_inline:
        return _error(
            "payload_invalid",
            f"{_EXCLUSIVE_GUIDANCE}. {BARE_PATH_GUIDANCE}",
            jsonpath="$.payload.artifact_handle",
        )
    inline_content: Optional[bytes] = None
    inline_filename: Optional[str] = None
    handle_text: Optional[str] = None
    parsed_handle: Optional[dict[str, Any]] = None
    if has_inline:
        try:
            inline_content, inline_filename = _decode_inline_bytes(
                payload.get("content_base64"),
                payload.get("filename"),
            )
        except (ArtifactHandleError, ValueError) as exc:
            path_key = (
                "$.payload.filename"
                if "filename" in str(exc) or "segment" in str(exc)
                else "$.payload.content_base64"
            )
            return _error("payload_invalid", str(exc), jsonpath=path_key)
    else:
        try:
            parsed_handle = parse_handle(payload.get("artifact_handle"))
            handle_text = serialize_handle(parsed_handle)
        except ArtifactHandleError as exc:
            return _error(
                "payload_invalid",
                f"{exc}. {BARE_PATH_GUIDANCE}",
                jsonpath="$.payload.artifact_handle",
            )
    conn = connect()
    try:
        try:
            stored_requirement_id = ensure_artifact_capacity(conn, run_id)
        except QaArtifactLimitError as exc:
            return _error("policy_violation", str(exc))
        if stored_requirement_id is None:
            return _error("not_found", f"run {run_id} not found")
        if stored_requirement_id != int(req_id):
            return _error(
                "target_invalid",
                f"run {run_id} belongs to requirement "
                f"{stored_requirement_id}, not {req_id}",
            )
        if parsed_handle is not None:
            try:
                refusal = _mission_handle_refusal(
                    conn,
                    req_id=int(req_id),
                    run_id=int(run_id),
                    handle=parsed_handle,
                )
            except LookupError as exc:
                return _error("not_found", str(exc))
            except ArtifactOwnerError as exc:
                return _error("target_invalid", str(exc))
            if refusal is not None:
                return _error(
                    "payload_invalid",
                    refusal,
                    jsonpath="$.payload.artifact_handle",
                )
        if has_inline:
            try:
                handle_text = _store_inline_bytes(
                    conn,
                    req_id=int(req_id),
                    run_id=int(run_id),
                    content=inline_content or b"",
                    filename=inline_filename or "",
                    content_type=content_type
                    if isinstance(content_type, str)
                    else None,
                )
            except LookupError as exc:
                return _error("not_found", str(exc))
            except ArtifactOwnerError as exc:
                return _error("target_invalid", str(exc))
            except ValueError as exc:
                return _error("target_invalid", str(exc))
            except OSError as exc:
                return _error(
                    "unavailable",
                    f"failed to store artifact bytes: {exc}",
                )
        cur = conn.execute(
            "INSERT INTO qa_artifacts "
            "(qa_run_id, artifact_type, content_type, artifact_handle, "
            "metadata, created_at) "
            f"VALUES ({_p(conn)}, {_p(conn)}, {_p(conn)}, {_p(conn)}, "
            f"{_p(conn)}, {_p(conn)}) RETURNING id",
            (
                int(run_id),
                artifact_type,
                content_type,
                handle_text,
                metadata,
                iso8601_now(),
            ),
        )
        artifact_id = int(cur.fetchone()[0])
        conn.commit()
    finally:
        conn.close()
    return HandlerOutcome(
        result_payload={"qa_artifact_id": artifact_id},
        primary_success=True,
    )


__all__ = [
    "QaArtifactAddRequest",
    "QaArtifactAddResponse",
    "handle_qa_artifact_add",
]
