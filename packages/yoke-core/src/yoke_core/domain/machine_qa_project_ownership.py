"""Durable case ownership for newly-created Machine QA fixture projects."""

from __future__ import annotations

import json

from yoke_contracts.qa_project_ownership import OWNER_CAPABILITY
from yoke_core.domain.db_helpers import iso8601_now, query_one


def assert_owner(conn, existing, owner):
    if not isinstance(owner, str) or not owner.strip():
        raise ValueError(
            "qa_project_owner_invalid: re-prepare the mission owner marker"
        )
    if existing is None:
        return
    row = query_one(
        conn,
        "SELECT settings FROM project_capabilities WHERE project_id=%s AND type=%s",
        (existing["id"], OWNER_CAPABILITY),
    )
    if row is None or json.loads(row["settings"]).get("owner") != owner:
        raise ValueError(
            "qa_project_owner_conflict: this project is not owned by the "
            "current machine case; choose a new test project slug"
        )


def mark_owner(conn, project_id, owner):
    conn.execute(
        "INSERT INTO project_capabilities (project_id, type, settings, created_at) "
        "VALUES (%s, %s, %s, %s)",
        (project_id, OWNER_CAPABILITY, json.dumps({"owner": owner}), iso8601_now()),
    )
