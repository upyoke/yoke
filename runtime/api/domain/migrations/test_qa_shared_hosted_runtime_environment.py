"""Regression coverage for the canonical hosted QA compatibility bridge."""

from __future__ import annotations

import pytest

from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.machine_qa_pack import sync_machine_qa_pack_methods
from yoke_core.domain.migrations.qa_execution_environment_target import (
    apply as apply_execution_target,
)
from yoke_core.domain.migrations.qa_execution_environment_target import (
    invariants as execution_target_invariants,
)
from yoke_core.domain.migrations.qa_hosted_runtime_environment import (
    apply as apply_hosted_runtime,
)
from yoke_core.domain.migrations.qa_hosted_runtime_environment import (
    invariants as hosted_runtime_invariants,
)
from yoke_core.domain.qa_execution_environment_target import (
    QaExecutionTargetError,
    resolve_plan_execution_target,
)
from yoke_core.domain.qa_plan_management import create_plan


def _unbound_installer_plan(conn) -> int:
    sync_machine_qa_pack_methods(conn)
    plan = create_plan(
        conn,
        project="yoke",
        slug="installer-campaign",
        name="Installer campaign",
    )
    conn.execute(
        "UPDATE qa_plans SET target_environment_id=NULL WHERE id=%s",
        (plan["id"],),
    )
    conn.commit()
    return int(plan["id"])


def _move_runtime_to_platform(conn, *, same_org: bool = True) -> None:
    conn.execute(
        "INSERT INTO environments(id,site,name,created_at,settings) "
        "VALUES('yoke-api-prod','yoke-api','prod',CURRENT_TIMESTAMP,'{}')"
    )
    yoke = conn.execute("SELECT org_id FROM projects WHERE slug='yoke'").fetchone()
    org_id = int(yoke["org_id"])
    if not same_org:
        other = conn.execute(
            "INSERT INTO organizations(slug,name,created_at) "
            "VALUES('other-org','Other org',CURRENT_TIMESTAMP) RETURNING id"
        ).fetchone()
        org_id = int(other["id"])
    platform = conn.execute(
        "INSERT INTO projects(id,org_id,slug,name,public_item_prefix,created_at) "
        "VALUES((SELECT MAX(id)+1 FROM projects),%s,'platform','Platform',"
        "'PLT',CURRENT_TIMESTAMP) "
        "RETURNING id",
        (org_id,),
    ).fetchone()
    conn.execute(
        "UPDATE sites SET project_id=%s WHERE id='yoke-api'",
        (int(platform["id"]),),
    )
    conn.commit()


def test_same_org_platform_runtime_converges_without_duplicate_site(
    monkeypatch,
) -> None:
    with test_database() as conn:
        plan_id = _unbound_installer_plan(conn)
        _move_runtime_to_platform(conn)
        monkeypatch.setenv("YOKE_ENVIRONMENT", "prod")

        apply_hosted_runtime(conn)
        hosted_runtime_invariants(conn)
        apply_execution_target(conn)
        execution_target_invariants(conn)

        target = resolve_plan_execution_target(conn, plan_id=plan_id)
        owner = conn.execute(
            "SELECT p.slug FROM sites s "
            "JOIN projects p ON p.id=s.project_id WHERE s.id='yoke-api'"
        ).fetchone()
        assert owner["slug"] == "platform"
        assert target["project"]["slug"] == "yoke"
        assert target["site"]["id"] == "yoke-api"
        assert target["environment"] == {"id": "yoke-api-prod", "name": "prod"}
        assert (
            conn.execute(
                "SELECT COUNT(*) AS total FROM sites WHERE id='yoke-api'"
            ).fetchone()["total"]
            == 1
        )


def test_cross_org_platform_runtime_is_refused(monkeypatch) -> None:
    with test_database() as conn:
        plan_id = _unbound_installer_plan(conn)
        _move_runtime_to_platform(conn, same_org=False)
        monkeypatch.setenv("YOKE_ENVIRONMENT", "prod")

        with pytest.raises(RuntimeError, match="unauthorized project"):
            apply_hosted_runtime(conn)
        conn.execute(
            "UPDATE qa_plans SET target_environment_id='yoke-api-prod' WHERE id=%s",
            (plan_id,),
        )
        conn.commit()
        with pytest.raises(QaExecutionTargetError, match="not authorized"):
            resolve_plan_execution_target(conn, plan_id=plan_id)
