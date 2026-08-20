"""QA catalog, plan management, and materialization contract tests."""

from __future__ import annotations

import json

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from runtime.api.qa_catalog_test_support import (
    CATALOG_CASES,
    create_release_readiness_plan,
)
from yoke_core.domain.qa_catalog_reads import (
    get_method,
    list_methods,
    list_plans,
)
from yoke_core.domain.qa_plan_attachments import attach_plan_to_item
from yoke_core.domain.qa_plan_detail import get_plan
from yoke_core.domain.qa_plan_management import (
    create_plan,
    replace_plan_cases,
)
from yoke_core.domain.qa_plan_project_defaults import set_project_default
from yoke_core.domain.schema_init_tables import create_governed_tables
from yoke_core.domain.machine_verification_schema import ensure_test_machine_schema


# The roster resolves a host lease through the registered resource name,
# so the capability row must name the machine its lease references.
MACHINE_SETTINGS = json.dumps(
    {
        "host": "test-mac.local",
        "operating_notes": "",
        "resource_name": "mac-mini-lab",
        "user": "yoke-test",
    },
    separators=(",", ":"),
    sort_keys=True,
)


def test_builtin_methods_seed_with_real_contracts() -> None:
    with test_database() as conn:
        rows = list_methods(conn, project="yoke")
        command = get_method(conn, method_id="command", project="yoke")
        command_ci = get_method(conn, method_id="command-ci", project="yoke")

    assert [row["id"] for row in rows] == [
        "command",
        "command-ci",
        "browser-check",
        "browser-inspection",
        "terminal-check",
        "terminal-inspection",
        "machine-state-check",
        "exploratory-mission",
    ]
    assert command["runner_id"] == "worktree_run"
    assert command["required_capability_kinds"] == []
    assert command["verdict_path"] == "automatic"
    assert command["required_capabilities"] == []
    # Same Command contract, executed on the project's CI workflow rather
    # than on this machine.
    assert command_ci["runner_id"] == "ci_run"
    assert command_ci["required_capability_kinds"] == []
    assert command_ci["verdict_path"] == "automatic"
    inspection = next(row for row in rows if row["id"] == "browser-inspection")
    assert inspection["description"] == (
        "Captures screenshots; an agent judges whether they show the "
        "case's expected outcome."
    )


def test_plan_cases_and_attachment_reads_are_project_scoped() -> None:
    with test_database() as conn:
        plan = create_release_readiness_plan(conn)
        item = insert_item(conn, id=2001, project_sequence=2001)
        attached = set_project_default(
            conn,
            plan_id=plan["id"],
            workflow_id="issue",
            transition_id="release",
        )
        attach_plan_to_item(
            conn,
            plan_id=plan["id"],
            item_id=int(item["id"]),
            transition_id="reviewing-implementation",
        )
        rows = list_plans(conn, project="yoke")
        detail = get_plan(conn, plan_id=plan["id"])
        methods = list_methods(conn, project="yoke")

    assert attached["transition_id"] == "release"
    assert len(rows) == 1
    assert rows[0]["case_count"] == 2
    assert rows[0]["materialized_requirement_count"] == 2
    assert rows[0]["attachments"] == [
        {
            "kind": "project_default",
            "project": "yoke",
            "workflow_id": "issue",
            "transition_id": "release",
            "item_id": None,
            "transition_label": "release",
        },
        {
            "kind": "item",
            "project": "yoke",
            "workflow_id": "issue",
            "transition_id": "reviewing-implementation",
            "item_id": 2001,
            "transition_label": "reviewing implementation",
            "item_ref": "YOK-2001",
        },
    ]
    assert [case["case_key"] for case in detail["cases"]] == [
        "backend-suite",
        "checkout-flow",
    ]
    command = next(row for row in methods if row["id"] == "command")
    assert command["used_by_plan_count"] == 1


def test_method_plan_roster_stays_inside_the_requested_project() -> None:
    with test_database() as conn:
        create_release_readiness_plan(conn)
        external = create_plan(
            conn,
            project="externalwebapp",
            slug="external-command",
            name="External command",
        )
        replace_plan_cases(
            conn,
            plan_id=external["id"],
            cases=[CATALOG_CASES[0]],
        )

        method = get_method(conn, method_id="command", project="yoke")

    assert [plan["project"] for plan in method["plans"]] == ["yoke"]
    assert [plan["slug"] for plan in method["plans"]] == [
        "release-readiness",
    ]


def test_machine_methods_and_plan_cases_project_the_active_serial_lease() -> None:
    with test_database() as conn:
        ensure_test_machine_schema(conn)
        create_governed_tables(conn)
        item = insert_item(
            conn,
            id=2101,
            project_sequence=2101,
            title="Exercise the Test Mac",
        )
        plan = create_plan(
            conn,
            project="yoke",
            slug="machine-readiness",
            name="Machine readiness",
        )
        replace_plan_cases(
            conn,
            plan_id=plan["id"],
            cases=[
                {
                    "case_key": "host-state",
                    "position": 1,
                    "method_id": "machine-state-check",
                    "instructions": "Inspect the controlled host.",
                    "expected_outcome": "The host state is ready.",
                    "method_config": {
                        "assertions": [{"argv": ["/usr/bin/true"]}],
                    },
                }
            ],
        )
        conn.execute(
            "INSERT INTO project_capabilities("
            "project_id,type,settings,verified_at,created_at"
            ") VALUES(1,'test-machine',%s,%s,%s) "
            "ON CONFLICT(project_id,type) DO UPDATE SET "
            "verified_at=EXCLUDED.verified_at",
            (
                MACHINE_SETTINGS,
                "2026-07-26T16:00:00Z",
                "2026-07-26T15:00:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO test_machine_verifications("
            "project_id,status,checked_at,receipt_json,error_code,updated_at"
            ") VALUES(1,'verified',%s,'{}',NULL,%s) "
            "ON CONFLICT(project_id) DO UPDATE SET "
            "status=EXCLUDED.status, checked_at=EXCLUDED.checked_at, "
            "updated_at=EXCLUDED.updated_at",
            ("2026-07-26T16:00:00Z", "2026-07-26T16:00:00Z"),
        )
        conn.execute(
            "INSERT INTO work_claims("
            "session_id,target_kind,item_id,claimed_at,last_heartbeat"
            ") VALUES('machine-session','item',%s,%s,%s)",
            (
                int(item["id"]),
                "2026-07-26T16:05:00Z",
                "2026-07-26T16:06:00Z",
            ),
        )
        conn.execute(
            "INSERT INTO coordination_leases("
            "id,project_id,lease_key,session_id,actor_id,"
            "acquired_at,heartbeat_at,released_at"
            ") VALUES(901,1,'QA_HOST:mac-mini-lab','machine-session','2',"
            "%s,%s,NULL)",
            ("2026-07-26T16:05:00Z", "2026-07-26T16:06:00Z"),
        )

        methods = list_methods(conn, project="yoke")
        detail = get_plan(conn, plan_id=plan["id"])
        conn.execute(
            "UPDATE coordination_leases SET released_at=%s WHERE id=901",
            ("2026-07-26T16:10:00Z",),
        )
        conn.execute(
            "UPDATE test_machine_verifications SET status='error' WHERE project_id=1",
        )
        error_state = next(
            row["required_capabilities"][0]["state"]
            for row in list_methods(
                conn,
                project="yoke",
            )
            if row["id"] == "machine-state-check"
        )
        conn.execute(
            "UPDATE test_machine_verifications "
            "SET status='configured_unverified' WHERE project_id=1",
        )
        configured_state = next(
            row["required_capabilities"][0]["state"]
            for row in list_methods(
                conn,
                project="yoke",
            )
            if row["id"] == "machine-state-check"
        )
        conn.execute(
            "UPDATE test_machine_verifications SET status='verified' "
            "WHERE project_id=1",
        )
        ready_state = next(
            row["required_capabilities"][0]["state"]
            for row in list_methods(
                conn,
                project="yoke",
            )
            if row["id"] == "machine-state-check"
        )
        conn.execute(
            "DELETE FROM test_machine_verifications WHERE project_id=1",
        )
        fallback_ready_state = next(
            row["required_capabilities"][0]["state"]
            for row in list_methods(
                conn,
                project="yoke",
            )
            if row["id"] == "machine-state-check"
        )
        conn.execute(
            "UPDATE project_capabilities SET verified_at=NULL "
            "WHERE project_id=1 AND type='test-machine'",
        )
        fallback_configured_state = next(
            row["required_capabilities"][0]["state"]
            for row in list_methods(
                conn,
                project="yoke",
            )
            if row["id"] == "machine-state-check"
        )
        conn.execute(
            "DELETE FROM project_capabilities "
            "WHERE project_id=1 AND type='test-machine'",
        )
        missing_state = next(
            row["required_capabilities"][0]["state"]
            for row in list_methods(
                conn,
                project="yoke",
            )
            if row["id"] == "machine-state-check"
        )
    expected_context = {
        "state": "in_use",
        "concurrency_mode": "serial",
        "wait_reason": "serial_lease_in_use",
        "active_lease": {"item_ref": "YOK-2101"},
    }
    machine_methods = [
        row for row in methods if "test-machine" in row["required_capability_kinds"]
    ]
    assert len(machine_methods) == 4
    scripted_machine_methods = [row for row in machine_methods
                                if row["runner_id"] == "host_control"]
    assert all(
        row["required_capabilities"]
        == [
            {
                "kind": "test-machine",
                "label": "Test Mac",
                "state": "in_use",
                "context": expected_context,
            }
        ]
        for row in scripted_machine_methods
    )
    mission = next(row for row in machine_methods if row["runner_id"] == "agent_mission")
    assert mission["required_capabilities"] == [
        {"kind": "browser-control", "label": "Browser control",
         "state": "not_configured", "context": {"state": "not_configured"}},
        {"kind": "test-machine", "label": "Test Mac", "state": "in_use",
         "context": expected_context},
    ]
    assert detail["cases"][0]["required_capabilities"] == [
        {
            "kind": "test-machine",
            "label": "Test Mac",
            "state": "in_use",
            "context": expected_context,
        }
    ]
    assert [
        error_state,
        configured_state,
        ready_state,
        fallback_ready_state,
        fallback_configured_state,
        missing_state,
    ] == [
        "error",
        "configured_unverified",
        "ready",
        "ready",
        "configured_unverified",
        "not_configured",
    ]
