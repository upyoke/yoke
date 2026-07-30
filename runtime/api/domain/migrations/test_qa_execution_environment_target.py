from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from psycopg.rows import tuple_row

from runtime.api.domain.migrations import (
    qa_execution_environment_target as source_wrapper,
)
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.api_urls import (
    DISTRIBUTION_PROD_URL,
    DISTRIBUTION_STAGE_URL,
    HOSTED_PLATFORM_URL,
    HOSTED_STAGE_PLATFORM_URL,
)
from yoke_core.domain.machine_qa_pack import sync_machine_qa_pack_methods
from yoke_core.domain.migrations.qa_execution_environment_target import (
    MIGRATION_NAME,
    apply,
    invariants,
)
from yoke_core.domain.migrations.qa_hosted_runtime_environment import (
    apply as apply_hosted_runtime_environment,
)
from yoke_core.domain.migrations.qa_hosted_runtime_environment import (
    invariants as hosted_runtime_environment_invariants,
)
from yoke_core.domain.migration_apply_manifest import validate_manifest_payload
from yoke_core.domain.qa_execution_environment_target import (
    QaExecutionTargetError,
    require_case_target,
    resolve_plan_execution_target,
)
from yoke_core.domain.qa_plan_management import create_plan
from yoke_core.domain.qa_plan_management import replace_plan_cases
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_execution_state import (
    QaPlanExecutionStateError,
    begin_plan_execution,
)

_ROOT = Path(__file__).resolve().parents[4]
_MANIFEST = Path(__file__).with_name("qa_execution_environment_target.migration.json")


def test_governed_manifest_is_valid_and_digest_bound() -> None:
    payload = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    validate_manifest_payload(payload)
    source = payload["module_sources"][MIGRATION_NAME]
    digest = hashlib.sha256((_ROOT / source["path"]).read_bytes()).hexdigest()
    assert digest == source["sha256"]


def test_source_checkout_wrapper_exposes_packaged_migration() -> None:
    assert source_wrapper.MIGRATION_NAME == MIGRATION_NAME
    assert source_wrapper.apply is apply
    assert source_wrapper.invariants is invariants


def _environment(conn, name: str) -> str:
    environment_id = f"yoke-api-{name}"
    conn.execute(
        "INSERT INTO environments(id,site,name,created_at,settings) "
        "VALUES(%s,'yoke-api',%s,'2026-07-29T00:00:00Z','{}') "
        "ON CONFLICT(id) DO UPDATE SET name=EXCLUDED.name",
        (environment_id, name),
    )
    conn.commit()
    return environment_id


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


@pytest.mark.parametrize(
    "runtime, expected_environment, installer_base, app_url, forbidden",
    [
        (
            "stage",
            "yoke-api-stage",
            DISTRIBUTION_STAGE_URL,
            HOSTED_STAGE_PLATFORM_URL,
            (DISTRIBUTION_PROD_URL, HOSTED_PLATFORM_URL),
        ),
        (
            "prod",
            "yoke-api-prod",
            DISTRIBUTION_PROD_URL,
            HOSTED_PLATFORM_URL,
            (DISTRIBUTION_STAGE_URL, HOSTED_STAGE_PLATFORM_URL),
        ),
    ],
)
def test_migration_binds_runtime_and_projects_installer_cases(
    monkeypatch,
    runtime,
    expected_environment,
    installer_base,
    app_url,
    forbidden,
) -> None:
    monkeypatch.setenv("YOKE_ENVIRONMENT", runtime)
    with test_database() as conn:
        _environment(conn, "stage")
        _environment(conn, "prod")
        plan_id = _unbound_installer_plan(conn)

        apply(conn)
        invariants(conn)
        target = resolve_plan_execution_target(conn, plan_id=plan_id)
        rows = conn.execute(
            "SELECT id,entry_surface,method_config,instructions "
            "FROM qa_plan_cases WHERE plan_id=%s ORDER BY position",
            (plan_id,),
        ).fetchall()
        first_ids = [int(row["id"]) for row in rows]
        rendered = json.dumps(
            [
                {
                    "entry_surface": row["entry_surface"],
                    "method_config": json.loads(row["method_config"]),
                    "instructions": row["instructions"],
                }
                for row in rows
            ],
            sort_keys=True,
        )

        assert target["environment"]["id"] == expected_environment
        assert target["environment"]["name"] == runtime
        assert target["tenant"]["slug"] == "default"
        assert target["project"]["slug"] == "yoke"
        assert target["endpoints"]["installer_base_url"] == installer_base
        assert target["endpoints"]["app_url"] == app_url
        assert installer_base in rendered
        assert app_url in rendered
        assert all(value not in rendered for value in forbidden)

        apply(conn)
        assert [
            int(row["id"])
            for row in conn.execute(
                "SELECT id FROM qa_plan_cases WHERE plan_id=%s ORDER BY position",
                (plan_id,),
            ).fetchall()
        ] == first_ids


def test_runtime_refuses_opposite_environment_target(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_ENVIRONMENT", "prod")
    with test_database() as conn:
        stage = _environment(conn, "stage")
        plan = create_plan(
            conn,
            project="yoke",
            slug="stage-plan",
            target_environment_id=None,
        )
        conn.execute(
            "UPDATE qa_plans SET target_environment_id=%s WHERE id=%s",
            (stage, plan["id"]),
        )
        conn.commit()
        with pytest.raises(QaExecutionTargetError, match="cannot execute"):
            resolve_plan_execution_target(conn, plan_id=plan["id"])


def test_migration_accepts_portable_tuple_row_connection(monkeypatch) -> None:
    monkeypatch.setenv("YOKE_ENVIRONMENT", "stage")
    with test_database() as conn:
        _environment(conn, "stage")
        _environment(conn, "prod")
        plan_id = _unbound_installer_plan(conn)
        conn.row_factory = tuple_row

        apply(conn)
        invariants(conn)

        target = resolve_plan_execution_target(conn, plan_id=plan_id)
        assert target["environment"]["name"] == "stage"


def test_migration_materializes_missing_hosted_runtime_environment(
    monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_ENVIRONMENT", "stage")
    with test_database() as conn:
        conn.execute("DELETE FROM environments WHERE site='yoke-api'")
        conn.execute("DELETE FROM sites WHERE id='yoke-api'")
        plan_id = _unbound_installer_plan(conn)

        apply_hosted_runtime_environment(conn)
        hosted_runtime_environment_invariants(conn)
        apply(conn)
        invariants(conn)

        target = resolve_plan_execution_target(conn, plan_id=plan_id)
        assert target["environment"] == {"id": "yoke-api-stage", "name": "stage"}
        assert target["endpoints"]["app_url"] == HOSTED_STAGE_PLATFORM_URL

        apply_hosted_runtime_environment(conn)
        hosted_runtime_environment_invariants(conn)


def test_hosted_runtime_environment_refuses_project_wide_duplicates(
    monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_ENVIRONMENT", "stage")
    with test_database() as conn:
        _environment(conn, "stage")
        _unbound_installer_plan(conn)
        conn.execute(
            "INSERT INTO sites(id,project_id,name,created_at,settings) "
            "VALUES('yoke-preview',1,'Yoke preview',CURRENT_TIMESTAMP,'{}')"
        )
        conn.execute(
            "INSERT INTO environments(id,site,name,created_at,settings) "
            "VALUES('yoke-preview-stage','yoke-preview','stage',"
            "CURRENT_TIMESTAMP,'{}')"
        )
        conn.commit()

        with pytest.raises(RuntimeError, match="multiple 'stage' environments"):
            apply_hosted_runtime_environment(conn)


def test_hosted_runtime_environment_ignores_unfounded_project(
    monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_ENVIRONMENT", "stage")
    with test_database() as conn:
        conn.execute("UPDATE projects SET slug='not-yoke' WHERE slug='yoke'")
        conn.commit()

        apply_hosted_runtime_environment(conn)
        hosted_runtime_environment_invariants(conn)
        assert (
            conn.execute(
                "SELECT id FROM environments WHERE id='yoke-api-stage'"
            ).fetchone()
            is None
        )


def test_case_guard_rejects_opposite_yoke_origin() -> None:
    target = {
        "environment": {"name": "prod"},
        "endpoints": {
            "app_url": HOSTED_PLATFORM_URL,
            "api_url": f"{HOSTED_PLATFORM_URL}/api/orgs/upyoke",
            "installer_base_url": DISTRIBUTION_PROD_URL,
            "installer_url": f"{DISTRIBUTION_PROD_URL}/install",
        },
    }
    with pytest.raises(QaExecutionTargetError, match="mixed-environment"):
        require_case_target(
            {"entry_surface": f"curl {DISTRIBUTION_STAGE_URL}/install"},
            target,
        )


def _command_plan(conn, *, slug: str, environment_id: str) -> int:
    plan = create_plan(
        conn,
        project="yoke",
        slug=slug,
        target_environment_id=environment_id,
    )
    replace_plan_cases(
        conn,
        plan_id=plan["id"],
        cases=[
            {
                "case_key": "command",
                "position": 1,
                "method_id": "command",
                "instructions": "Run the command.",
                "expected_outcome": "It passes.",
                "method_config": {"command": "true"},
            }
        ],
    )
    set_project_default(
        conn,
        plan_id=plan["id"],
        workflow_id="issue",
        transition_id="implemented",
    )
    return int(plan["id"])


def test_materialization_snapshots_target_and_mixed_roster_is_refused(
    monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_ENVIRONMENT", "development")
    with test_database() as conn:
        stage = _environment(conn, "stage")
        prod = _environment(conn, "prod")
        insert_item(conn, id=811, title="Targeted QA", workflow_id="issue")
        _command_plan(conn, slug="stage-command", environment_id=stage)
        _command_plan(conn, slug="prod-command", environment_id=prod)

        materialized = materialize_for_item(
            conn,
            item_id=811,
            transition_id="implemented",
        )
        snapshots = conn.execute(
            "SELECT execution_target_json,execution_target_digest "
            "FROM qa_requirements WHERE id=ANY(%s) ORDER BY id",
            (materialized["created_requirement_ids"],),
        ).fetchall()
        assert {
            json.loads(row["execution_target_json"])["environment"]["name"]
            for row in snapshots
        } == {"stage", "prod"}
        assert all(row["execution_target_digest"] for row in snapshots)

        with pytest.raises(
            QaPlanExecutionStateError,
            match="mixes execution environment targets",
        ):
            begin_plan_execution(
                conn,
                item_id=811,
                transition_id="implemented",
                actor_id="actor-1",
                session_id="session-1",
            )
