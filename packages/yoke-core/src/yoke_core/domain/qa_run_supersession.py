"""Recognize abandoned CI attempts without relaxing verdict immutability."""

from __future__ import annotations

import json

from yoke_contracts.api.function_call import HandlerOutcome
from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one


def superseded_run_outcome(conn, run_id, requirement_id, ignored_verdict=None):
    """Return a write-free receipt only for an explicitly replaced error run."""
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    lock = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    row = query_one(
        conn,
        f"SELECT verdict, raw_result FROM qa_runs WHERE id = {p} "
        f"AND qa_requirement_id = {p}{lock}",
        (int(run_id), int(requirement_id)),
    )
    if row is None or row["verdict"] != "error":
        return None
    try:
        raw = json.loads(row["raw_result"] or "{}")
    except (TypeError, ValueError):
        return None
    if not isinstance(raw, dict) or "replacement_ci_run_id" not in raw:
        return None
    newer = query_one(
        conn,
        f"SELECT id FROM qa_runs WHERE qa_requirement_id = {p} AND id > {p} LIMIT 1",
        (int(requirement_id), int(run_id)),
    )
    if newer is None:
        return None
    return HandlerOutcome(
        primary_success=True,
        result_payload={
            "qa_run_id": int(run_id),
            "already_settled": True,
            "verdict": row["verdict"],
            "ignored_verdict": ignored_verdict,
        },
    )
