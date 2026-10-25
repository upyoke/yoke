"""Capture and preserve the lane commit at the start of every item QA run."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.db_helpers import query_one
from yoke_core.domain.qa_merging_identity import recorded_head_sha
from yoke_core.domain.qa_run_commit_binding import wrap_evidence
from yoke_core.domain.schema_common import _column_exists, _table_exists


def stamp_start_commit(conn: Any, columns: dict[str, Any]) -> None:
    if recorded_head_sha(columns.get("raw_result")):
        return
    if not _table_exists(conn, "item_worktrees") or not _column_exists(
        conn, "qa_requirements", "item_id"
    ):
        return
    deployment = (
        "deployment_run_id"
        if _column_exists(conn, "qa_requirements", "deployment_run_id")
        else "NULL AS deployment_run_id"
    )
    phase = (
        "qa_phase"
        if _column_exists(conn, "qa_requirements", "qa_phase")
        else "NULL AS qa_phase"
    )
    subject = query_one(
        conn,
        f"SELECT {deployment},{phase} FROM qa_requirements WHERE id=%s",
        (int(columns["qa_requirement_id"]),),
    )
    if (
        not subject
        or subject.get("deployment_run_id")
        or subject.get("qa_phase") == "post_deploy"
    ):
        return
    row = query_one(
        conn,
        "SELECT w.commit_sha,w.path FROM item_worktrees w "
        "JOIN qa_requirements q ON q.item_id=w.item_id "
        "WHERE q.id=%s AND w.state='active' ORDER BY w.id DESC LIMIT 1",
        (int(columns["qa_requirement_id"]),),
    )
    if row and row.get("commit_sha"):
        columns["raw_result"] = wrap_evidence(
            columns.get("raw_result"),
            str(row["commit_sha"]),
            root=str(row["path"] or ""),
        )


def retain_start_commit(existing_raw: Any, incoming_raw: Any) -> Any:
    if recorded_head_sha(incoming_raw):
        return incoming_raw
    sha = recorded_head_sha(existing_raw)
    return wrap_evidence(incoming_raw, sha) if sha else incoming_raw
