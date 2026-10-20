"""Only profile inputs reopen the confirmed setup profile; setup writes do not."""

from __future__ import annotations

from yoke_contracts.onboard_checklist import BRANCH_LOCAL_CHECKOUT
from yoke_core.domain.project_onboarding_configuration import (
    profile_changed,
    project_facts,
)
from yoke_core.domain.project_onboarding_runs import get_run, init_run, update_run
from yoke_core.domain.project_structure import create_project_structure_tables
from yoke_core.domain.project_structure_write import apply_patch_on_connection
from yoke_core.domain.qa_plan_management import create_plan
from yoke_core.domain.workflow_project_defaults import (
    set_delivery_default,
    set_testing_default,
)

STAMP = "2026-07-26T00:00:00Z"


def _save_profile(conn, run_id):
    init_run(conn=conn, run_id=run_id, project_id=1, branch=BRANCH_LOCAL_CHECKOUT)
    update_run(
        run_id=run_id,
        project_id=1,
        conn=conn,
        metadata={"execution_profile": {"delivery": "persistent"}},
    )
    assert get_run(run_id, conn=conn)["profile_changed"] is False


def _human_interview(conn, run_id):
    rows = get_run(run_id, conn=conn)["rows"]
    return next(row for row in rows if row["row_id"] == "human-interview")


def _seed_delivery_flow(conn):
    conn.execute(
        "INSERT INTO environments(site, project_id, name, created_at) "
        "SELECT id, 1, 'prod', %s FROM sites WHERE project_id=1 "
        "ORDER BY id LIMIT 1 ON CONFLICT(project_id,name) DO NOTHING",
        (STAMP,),
    )
    conn.execute(
        "INSERT INTO deployment_flows("
        "id, project_id, name, description, stages, on_failure, created_at, "
        "status, target_tier, target_environment_id"
        ") VALUES ('profile-prod', 1, 'Profile prod', '', '[]', 'halt', %s, "
        "'active', 'persistent', (SELECT id FROM environments "
        "WHERE project_id=1 AND name='prod'))",
        (STAMP,),
    )
    conn.commit()


def test_later_setup_writes_and_strategy_edits_keep_the_profile(test_db):
    create_project_structure_tables(test_db)
    _seed_delivery_flow(test_db)
    test_db.execute(
        "INSERT INTO strategy_docs (project_id, slug, content, updated_at) "
        "VALUES (1, 'MISSION', 'First mission.', %s)",
        (STAMP,),
    )
    test_db.commit()
    _save_profile(test_db, "profile-setup-writes")

    set_delivery_default(
        test_db, project="yoke", workflow_id="dash", flow_id="profile-prod"
    )
    plan = create_plan(test_db, project="yoke", slug="profile", name="Profile")
    set_testing_default(
        test_db, project="yoke", workflow_id="issue", plan_id=plan["id"], actor_id=1
    )
    test_db.execute(
        "UPDATE strategy_docs SET content = 'Edited mission.' "
        "WHERE project_id = 1 AND slug = 'MISSION'"
    )
    test_db.commit()

    run = get_run("profile-setup-writes", conn=test_db)
    rows = {row["row_id"]: row for row in run["rows"]}
    assert run["profile_changed"] is False
    assert rows["delivery-setup"]["status"] == "configured"
    assert rows["verification-command-binding"]["status"] == "configured"
    assert rows["human-interview"]["status"] == "configured"


def test_a_changed_hosting_declaration_still_reopens_the_profile(test_db):
    create_project_structure_tables(test_db)
    _save_profile(test_db, "profile-hosting")

    apply_patch_on_connection(
        test_db,
        "yoke",
        ops=[
            {
                "op": "put",
                "family": "hosting_posture",
                "attachment": "project",
                "payload": {
                    "posture": "no-yoke-managed-host",
                    "provider": "existing-provider",
                },
            }
        ],
    )
    test_db.commit()

    assert get_run("profile-hosting", conn=test_db)["profile_changed"] is True
    row = _human_interview(test_db, "profile-hosting")
    assert row["status"] == "unknown"
    assert row["reason"] == "setup_profile_changed"


def test_a_snapshot_holding_retired_inputs_compares_only_profile_rows(test_db):
    facts = project_facts(test_db, 1)
    snapshot = {
        **facts,
        "strategy-setup": {"status": "unknown", "evidence": {"content_sha256": "x"}},
        "delivery-setup": {"status": "unknown", "evidence": {"settings_sha256": "y"}},
    }
    assert profile_changed(snapshot, facts) is False
    snapshot["project-identity"] = {"status": "unknown"}
    assert profile_changed(snapshot, facts) is True
