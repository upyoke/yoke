"""Include question-owned QA artifact handles in universe portability."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_core.domain.qa_artifact_handle import build_artifact_key, parse_handle
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.universe_archive import UniverseArchiveError


def question_sources(conn):
    if not _table_exists(conn, "decision_requests"):
        return []
    result = []
    for request_id, project, raw in conn.execute(
        "SELECT d.id,p.slug,d.subject_context FROM decision_requests d "
        "JOIN projects p ON p.id=d.project_id WHERE d.kind='operator_question' ORDER BY d.id"
    ).fetchall():
        context = json.loads(raw) if isinstance(raw, str) else raw
        for artifact in context.get("artifacts", []):
            handle = parse_handle(artifact["artifact_handle"])
            filename = Path(handle.get("path") or handle["key"]).name
            result.append(
                {
                    "question_request_id": int(request_id),
                    "artifact_id": artifact["artifact_id"],
                    "project": project,
                    "original_handle": handle,
                    "key": build_artifact_key(
                        project,
                        f"decision-request-{request_id}",
                        int(request_id),
                        filename,
                    ),
                }
            )
    return result


def question_entry(conn, entry, replacement=None):
    """Verify the dump's exact ref, then replace it in the restore transaction."""
    request_id = entry["question_request_id"]
    row = conn.execute(
        "SELECT d.subject_context,p.slug FROM decision_requests d "
        "JOIN projects p ON p.id=d.project_id WHERE d.id=%s AND d.kind='operator_question'",
        (request_id,),
    ).fetchone()
    if row is None or row[1] != entry["project"]:
        raise UniverseArchiveError(
            "archive_artifact_owner_missing: question owner differs from the dump; export again"
        )
    context = json.loads(row[0]) if isinstance(row[0], str) else row[0]
    artifact = next(
        (
            a
            for a in context.get("artifacts", [])
            if a["artifact_id"] == entry["artifact_id"]
        ),
        None,
    )
    if artifact is None or parse_handle(artifact["artifact_handle"]) != parse_handle(
        entry["original_handle"]
    ):
        raise UniverseArchiveError(
            "archive_artifact_handle_mismatch: question attachment differs from the dump; export again"
        )
    if replacement is not None:
        artifact["artifact_handle"] = replacement
        conn.execute(
            "UPDATE decision_requests SET subject_context=%s WHERE id=%s",
            (json.dumps(context, separators=(",", ":")), request_id),
        )
