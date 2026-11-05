# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import pytest

from yoke_core.domain.qa_execution_environment_target import (
    target_digest,
)

from yoke_core.domain.qa_plan_management import QaPlanError

from yoke_core.domain.qa_plan_requirement_snapshot import require_existing_target

from yoke_core.domain.qa_requirement_pass_currency import (
    attach_execution_target_digest,
    has_current_passing_run,
)

from yoke_core.domain.qa_requirement_rebind_endpoint_delta import endpoint_delta

from yoke_core.domain.qa_requirement_target_rebind import (
    QaRebindError,
    rebind_requirement,
)

from yoke_core.domain.settings_cas import (
    apply_key_path_assignments,
    parse_settings_object,
)

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement, insert_qa_run

from runtime.api.fixtures.pg_testdb import test_database


def _yoke_development(conn):
    return conn.execute(
        "SELECT e.id FROM environments e JOIN sites s ON s.id=e.site "
        "JOIN projects p ON p.id=s.project_id "
        "WHERE p.slug='yoke' AND e.name='development'"
    ).fetchone()[0]


def _identity(conn, environment_id):
    from yoke_core.domain.qa_requirement_rebind_identity import _identity_row

    return _identity_row(conn, environment_id)


def _hosted_prod_pair(conn) -> tuple[int, int]:
    """Yoke plan project owns `prod`; hosted Yoke API also owns `prod`."""
    conn.execute("UPDATE sites SET name='yoke' WHERE project_id=1")
    conn.execute(
        "INSERT INTO projects"
        "(id,slug,name,github_repo,public_item_prefix,org_id,created_at) "
        "VALUES (3,'platform','Platform','upyoke/platform','PLAT',1,"
        "'2026-01-01T00:00:00Z') ON CONFLICT(id) DO NOTHING"
    )
    conn.execute(
        "INSERT INTO sites(project_id,name,created_at) "
        "VALUES (3,'Yoke API','2026-01-01T00:00:00Z')"
    )
    hosted = json.dumps(
        {
            "qa": {"hosted_runtime": True, "hosted_runtime_consumer": "yoke"},
            "hosts": {"app": "http://app.upyoke.com", "api": "https://api.upyoke.com"},
            "distribution": {
                "base_url": "https://dist.example.test",
                "channel": "prod",
            },
        }
    )
    for project_id, site_name, settings in (
        (3, "Yoke API", hosted),
        (1, "yoke", json.dumps({"hosts": {"app": "https://yoke.example.test"}})),
    ):
        conn.execute(
            "INSERT INTO environments(site,project_id,name,settings,created_at) "
            "SELECT id,%s,'prod',%s,'2026-01-01T00:00:00Z' FROM sites "
            "WHERE project_id=%s AND name=%s",
            (project_id, settings, project_id, site_name),
        )
    conn.commit()

    def _id(site: str) -> int:
        row = conn.execute(
            "SELECT e.id FROM environments e JOIN sites s ON s.id=e.site "
            "WHERE s.name=%s AND e.name='prod'",
            (site,),
        ).fetchone()
        return int(row["id"] if hasattr(row, "keys") else row[0])

    return _id("Yoke API"), _id("yoke")


def _stamp_requirement(
    conn,
    *,
    item_id: int,
    environment_id: int,
    plan_id: int | None = None,
    target: dict | None = None,
) -> int:
    from yoke_core.domain.qa_environment_execution_target import (
        environment_execution_target,
    )
    from yoke_core.domain.qa_execution_environment_target import canonical_target

    insert_item(conn, id=item_id, title="Bound case", workflow_id="issue")
    if target is None:
        identity = _identity(conn, environment_id)
        target = environment_execution_target(
            conn, identity, require_runtime_match=False
        )
    digest = target_digest(target)
    extra = {}
    if plan_id is not None:
        extra["plan_id"] = int(plan_id)
    row = insert_qa_requirement(
        conn,
        item_id=item_id,
        qa_kind="command",
        execution_target_json=canonical_target(target),
        execution_target_digest=digest,
        **extra,
    )
    insert_qa_run(
        conn,
        qa_requirement_id=int(row["id"]),
        verdict="pass",
        raw_result=attach_execution_target_digest("{}", digest),
    )
    return int(row["id"])
