"""``qa.artifact.add`` — record a typed handle or store inline evidence bytes."""

from __future__ import annotations

from yoke_core.domain.agent_mission_restore import hand_back_mission_walk
from yoke_core.domain.qa_run_supersession import superseded_run_outcome

import base64
import binascii
from pathlib import Path
from typing import Any, Optional

from yoke_contracts.api.function_call import FunctionCallRequest, HandlerOutcome
from yoke_core.domain.qa_handler_outcomes import _error, _p
from yoke_core.domain.qa_browser_write_models import (
    QaArtifactAddRequest,
    QaArtifactAddResponse,
)

_EXCLUSIVE_GUIDANCE = "pass artifact_handle or content_base64 plus filename, not both"


def _decode_inline_bytes(raw: object, filename: object) -> tuple[bytes, str]:
    from yoke_core.domain.qa_artifact_storage import MAX_ARTIFACT_BYTES
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
    if len(content) > MAX_ARTIFACT_BYTES:
        raise ValueError(
            f"inline content is {len(content)} bytes; limit is {MAX_ARTIFACT_BYTES}"
        )
    return content, safe_segment(filename)


def _store_inline_bytes(
    conn,
    *,
    req_id: int,
    run_id: int,
    content: bytes,
    filename: str,
    content_type: Optional[str],
) -> str:
    from yoke_core.domain.qa_artifact_handle import serialize_handle
    from yoke_core.domain.qa_artifact_storage import (
        store_artifact_bytes,
    )

    return serialize_handle(
        store_artifact_bytes(
            conn,
            requirement_id=req_id,
            run_id=run_id,
            filename=filename,
            content=content,
            content_type=content_type,
        )
    )


def handle_qa_artifact_add(request: FunctionCallRequest) -> HandlerOutcome:
    """Commit the artifact before retrying settlement for a deployment pass."""
    from yoke_contracts.api.function_call import FunctionWarning
    from yoke_core.domain.db_helpers import connect, query_one
    from yoke_core.domain.qa_run_execution_evidence import (
        VerdictSettlementRefused,
        commit_settled_verdict,
    )

    conn = connect()
    try:
        outcome = record_qa_artifact(conn, request)
        if not outcome.primary_success:
            return outcome
        conn.commit()
        run_id = (request.payload or {}).get("run_id")
        if "qa_artifact_id" in outcome.result_payload and query_one(
            conn,
            "SELECT 1 FROM qa_runs r JOIN qa_requirements q ON q.id=r.qa_requirement_id "
            f"WHERE r.id={_p(conn)} AND r.verdict='pass' AND q.deployment_run_id IS NOT NULL",
            (run_id,),
        ):
            try:
                commit_settled_verdict(conn, run_id)
            except VerdictSettlementRefused as exc:
                outcome.warnings.append(
                    FunctionWarning(
                        code=exc.code,
                        step="deployment_qa_settlement",
                        detail=f"The artifact is recorded. {exc}",
                    )
                )
        return outcome
    finally:
        conn.close()


def record_qa_artifact(
    conn: Any, request: FunctionCallRequest, *, locked_execution: dict | None = None
) -> HandlerOutcome:
    """Record one artifact in the caller's transaction; never commits.

    A refusal leaves the caller's transaction for the caller to roll back.
    ``locked_execution`` is an execution the caller already holds FOR UPDATE;
    the walk hand-back reuses it rather than locking it a second time.
    """
    from yoke_core.domain.db_helpers import (
        instant_parameter,
        utc_now,
        query_one,
    )
    from yoke_core.domain.qa_artifact_handle import (
        ArtifactHandleError,
        parse_handle,
        serialize_handle,
    )
    from yoke_core.domain.qa_artifact_local_handle import local_handle_refusal
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
    has_handle = payload.get("artifact_handle") not in (None, "")
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
    if settled := superseded_run_outcome(conn, run_id, req_id):
        return settled
    if parsed_handle is not None:
        try:
            refusal = local_handle_refusal(
                conn,
                req_id=int(req_id),
                run_id=int(run_id),
                handle=parsed_handle,
            )
        except LookupError as exc:
            return _error("not_found", str(exc))
        except ValueError as exc:
            return _error("target_invalid", str(exc))
        if refusal is not None:
            return _error(
                "payload_invalid",
                refusal,
                jsonpath="$.payload.artifact_handle",
            )
        if parsed_handle.get("backend") == "s3":
            from yoke_core.domain.qa_artifact_storage import (
                ArtifactStorageError,
                validate_s3_handle_owner,
            )

            try:
                validate_s3_handle_owner(
                    conn,
                    requirement_id=int(req_id),
                    run_id=int(run_id),
                    handle=parsed_handle,
                )
            except ArtifactStorageError as exc:
                return _error(exc.code, str(exc))
        if parsed_handle.get("backend") == "local":
            from yoke_core.domain.qa_artifact_storage import (
                ArtifactStorageError,
                store_artifact_file,
            )

            try:
                stored_handle = store_artifact_file(
                    conn,
                    requirement_id=int(req_id),
                    run_id=int(run_id),
                    path=str(parsed_handle["path"]),
                    filename=Path(str(parsed_handle["path"])).name,
                    content_type=(
                        str(parsed_handle.get("content_type") or content_type)
                        if parsed_handle.get("content_type") or content_type
                        else None
                    ),
                )
                handle_text = serialize_handle(stored_handle)
            except ArtifactStorageError as exc:
                return _error(exc.code, str(exc))
            except ValueError as exc:
                return _error("payload_invalid", str(exc))
    if has_inline:
        from yoke_core.domain.qa_artifact_storage import ArtifactStorageError

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
        except ArtifactStorageError as exc:
            return _error(exc.code, str(exc))
        except ValueError as exc:
            return _error("target_invalid", str(exc))
    # ensure_artifact_capacity holds FOR UPDATE on this qa_runs row
    # until commit, so a retry racing a still-running writer waits,
    # then sees the inserted handle. No extra unique index.
    existing = query_one(
        conn,
        "SELECT id FROM qa_artifacts "
        f"WHERE qa_run_id = {_p(conn)} AND artifact_handle = {_p(conn)}",
        (int(run_id), handle_text),
    )
    if existing is not None:
        artifact_id = int(existing["id"])
    else:
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
                instant_parameter(conn, utc_now()),
            ),
        )
        artifact_id = int(cur.fetchone()[0])
    hand_back_mission_walk(
        conn,
        artifact_type=artifact_type,
        run_id=run_id,
        locked_execution=locked_execution,
    )
    if artifact_type == "starting_state_restore":
        from yoke_core.domain.machine_restore_debt import record_restore_artifact

        record_restore_artifact(
            conn, int(req_id), run_id, inline_content, request.actor,
            new_artifact_id=artifact_id if existing is None else None,
        )
    return HandlerOutcome(
        result_payload={"qa_artifact_id": artifact_id},
        primary_success=True,
    )


__all__ = [
    "QaArtifactAddRequest",
    "QaArtifactAddResponse",
    "handle_qa_artifact_add",
    "record_qa_artifact",
]
