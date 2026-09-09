"""Attach default human-approval addresses on SQL-seeded deployment flows.

Direct INSERT into ``deployment_flows`` bypasses write-time
``require_human_approval_addresses``. Evaluate-path tests call this after
seed so the gate has roles to consult. Do not use this in tests that
assert fail-closed missing approvers.
"""

from __future__ import annotations

import json
from typing import Any, Iterator

from yoke_core.domain import db_backend

DEFAULT_STAGE_APPROVALS = {"roles": ["owner", "operator"], "actors": []}


def attach_default_human_approval_addresses(conn: Any) -> None:
    placeholder = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute("SELECT id, stages FROM deployment_flows").fetchall()
    for row in rows:
        raw = row["stages"]
        stages = json.loads(raw) if isinstance(raw, str) else list(raw)
        changed = False
        patched = []
        for stage in stages:
            entry = dict(stage)
            if (
                entry.get("step_runner") == "human-approval"
                and "approvals" not in entry
            ):
                entry["approvals"] = dict(DEFAULT_STAGE_APPROVALS)
                changed = True
            patched.append(entry)
        if changed:
            conn.execute(
                f"UPDATE deployment_flows SET stages = {placeholder} "
                f"WHERE id = {placeholder}",
                (json.dumps(patched), row["id"]),
            )
    conn.commit()


def seed_stage_approval(conn: Any) -> dict[str, Any]:
    """Seed one executing run suspended at a human-approval stage.

    Returns the identities its callers assert on: the run, its one batch
    member, and the actors who created and may answer the gate. One helper so
    a second test file does not re-author the same flow, run and membership.
    """
    from yoke_core.domain.decision_request_schema import (
        create_decision_request_tables,
    )

    create_decision_request_tables(conn)
    conn.execute(
        "INSERT INTO sites(project_id, name, created_at) "
        "VALUES (1, 'Approval test site', '2026-07-26T00:00:00Z') "
        "ON CONFLICT(project_id, name) DO NOTHING"
    )
    conn.execute(
        "INSERT INTO environments(site, project_id, name, created_at) "
        "SELECT id, 1, 'prod', '2026-07-26T00:00:00Z' FROM sites "
        "WHERE project_id=1 AND name='Approval test site' "
        "ON CONFLICT(project_id, name) DO NOTHING"
    )
    environment_id = conn.execute(
        "SELECT id FROM environments WHERE project_id=1 AND name='prod'"
    ).fetchone()[0]
    originator = conn.execute("SELECT id FROM actors ORDER BY id LIMIT 1").fetchone()[0]
    owner = conn.execute("SELECT id FROM actors ORDER BY id DESC LIMIT 1").fetchone()[0]
    role = conn.execute(
        "INSERT INTO roles (id, name, description, created_at) "
        "VALUES (9301, 'owner', 'Owner', '2026-07-26T00:00:00Z') "
        "ON CONFLICT(name) DO UPDATE SET description=EXCLUDED.description "
        "RETURNING id"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO actor_project_roles "
        "(actor_id, project_id, role_id, granted_at) "
        "VALUES (%s, 1, %s, '2026-07-26T00:00:00Z') "
        "ON CONFLICT DO NOTHING",
        (owner, role),
    )
    conn.execute(
        "INSERT INTO deployment_flows "
        "(id, project_id, name, stages, created_at) "
        "VALUES ('approval-proof', 1, 'Approval proof', "
        '\'[{"name":"approve-prod","step_runner":"human-approval",'
        '"approvals":{"roles":["owner","operator"],"actors":[]}},'
        '{"name":"release","step_runner":"auto"}]\', '
        "'2026-07-26T00:00:00Z')"
    )
    conn.execute(
        "INSERT INTO deployment_runs "
        "(id, project_id, flow, target_tier, target_environment_id, "
        "release_lineage, status, current_stage, created_at) "
        "VALUES ('run-approval-proof', 1, 'approval-proof', 'persistent', "
        "%s, 'release-proof-lineage', 'executing', 'approve-prod', "
        "'2026-07-26T00:00:00Z')",
        (environment_id,),
    )
    workflow = conn.execute(
        "SELECT current_version_id FROM workflows WHERE id='issue'"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO items "  # lint:no-lifecycle-mutation-check
        "(id, title, status, priority, created_at, updated_at, source, owner, "
        "project_id, project_sequence, workflow_id, workflow_version_id) "
        "VALUES (9601, 'Deployment batch member', 'implemented', 'medium', "
        "'2026-07-26T00:00:00Z', '2026-07-26T00:00:00Z', %s, %s, "
        "1, 9601, 'issue', %s)",
        (str(originator), str(owner), workflow),
    )
    member = conn.execute(
        "SELECT i.id, i.project_sequence, i.title, p.slug, p.public_item_prefix "
        "FROM items i JOIN projects p ON p.id=i.project_id "
        "WHERE i.id=9601"
    ).fetchone()
    conn.execute(
        "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
        "VALUES ('run-approval-proof', %s, '2026-07-26T00:00:00Z')",
        (int(member[0]),),
    )
    conn.commit()
    return {
        "run_id": "run-approval-proof",
        "stage": "approve-prod",
        "environment_id": int(environment_id),
        "originator": originator,
        "owner": owner,
        "member": member,
    }


def gate_environment_id(conn, *, environment: str = "prod") -> int:
    conn.execute(
        "INSERT INTO sites(project_id, name, created_at) "
        "VALUES (1, 'Gate test site', '2026-07-26T00:00:00Z') "
        "ON CONFLICT(project_id, name) DO NOTHING"
    )
    conn.execute(
        "INSERT INTO environments(site, project_id, name, created_at) "
        "SELECT id, 1, %s, '2026-07-26T00:00:00Z' FROM sites "
        "WHERE project_id=1 AND name='Gate test site' "
        "ON CONFLICT(project_id, name) DO NOTHING",
        (environment,),
    )
    return int(
        conn.execute(
            "SELECT id FROM environments WHERE project_id=1 AND name=%s",
            (environment,),
        ).fetchone()[0]
    )


def seed_gate_run(
    conn,
    *,
    flow_id,
    run_id,
    stages_json,
    created_by="1",
    environment="prod",
    current_stage="approve-prod",
):
    environment_id = gate_environment_id(conn, environment=environment)
    conn.execute(
        "INSERT INTO deployment_flows "
        "(id, project_id, name, stages, created_at) "
        "VALUES (%s, 1, %s, %s, '2026-07-26T00:00:00Z')",
        (flow_id, flow_id, stages_json),
    )
    conn.execute(
        "INSERT INTO deployment_runs "
        "(id, project_id, flow, target_tier, target_environment_id, "
        "status, current_stage, created_by, created_at) "
        "VALUES (%s, 1, %s, 'persistent', %s, 'executing', "
        "%s, %s, '2026-07-26T00:00:00Z')",
        (run_id, flow_id, environment_id, current_stage, created_by),
    )
    conn.commit()


class OpenConnection:
    """Keep the fixture-owned connection open across runtime helper calls.

    The approval helpers open and close their own connection; a test driving
    them against a fixture connection must survive that ``close()``.
    """

    def __init__(self, conn: Any):
        self._conn = conn

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def close(self) -> None:
        return None


def yield_seeded_api_db_with_default_approvals() -> Iterator[dict[str, str]]:
    from runtime.api.api_items_test_helpers import make_test_db_fixture
    from runtime.api.fixtures.file_test_db import connect_test_db

    for db in make_test_db_fixture():
        conn = connect_test_db(db["db_path"])
        try:
            attach_default_human_approval_addresses(conn)
        finally:
            conn.close()
        yield db
