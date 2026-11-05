"""Question-owned references to files in the existing QA evidence store."""

from __future__ import annotations

import json

from yoke_contracts.operator_question_attachments import validate_uploads
from yoke_core.domain.qa_artifact_storage import store_owned_artifact_bytes


def owner(conn, request):
    from yoke_core.domain.project_identity import resolve_project_slug

    return {
        "project_id": request["project_id"],
        "project": resolve_project_slug(conn, request["project_id"]),
        "artifact_subject": f"decision-request-{request['id']}",
        "target_env": None,
    }


def attach_files(conn, request, uploads):
    from yoke_core.domain.decision_requests import _p
    from yoke_core.domain.decision_request_rows import request_row

    stored = []
    storage_owner = owner(conn, request)
    for index, (filename, content_type, content) in enumerate(
        validate_uploads(uploads), 1
    ):
        handle = store_owned_artifact_bytes(
            conn,
            owner=storage_owner,
            run_id=request["id"],
            filename=f"{index}-{filename}",
            content=content,
            content_type=content_type,
        )
        stored.append(
            {
                "artifact_id": index,
                "decision_request_id": request["id"],
                "artifact_type": "screenshot"
                if content_type.startswith("image/")
                else "document",
                "content_type": content_type,
                "artifact_handle": handle,
                "metadata": {"label": filename, "filename": filename},
            }
        )
    context = {**request["subject_context"], "artifacts": stored}
    conn.execute(
        f"UPDATE decision_requests SET subject_context={_p(conn)} WHERE id={_p(conn)}",
        (json.dumps(context, separators=(",", ":")), request["id"]),
    )
    return request_row(conn, request["id"])
