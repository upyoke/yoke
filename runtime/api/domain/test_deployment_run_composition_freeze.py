"""Frozen deployment candidate, membership, intent, and QA inputs."""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement
from yoke_core.domain import deployment_run_composition_freeze as composition
from yoke_core.domain.deployment_runs_crud_mutate import (
    cmd_add_item,
    cmd_remove_item,
    cmd_update,
)
from yoke_core.domain.flow_create import cmd_create
from yoke_core.domain.workflow_project_defaults import set_delivery_default


ADVANCED_STAGES = json.dumps(
    [
        {
            "name": "stage",
            "step_runner": "auto",
            "stage_kind": "execution",
            "scope": "run",
        },
        {
            "name": "item-qa",
            "step_runner": "qa",
            "stage_kind": "qa",
            "scope": "item",
            "target": dict(kind="persistent_environment", environment="stage",
                           source_stage="stage"),
            "verdict": {"mode": "agent_only"},
        },
    ]
)


def _environment(conn: Any) -> None:
    conn.execute(
        "INSERT INTO environments(site,project_id,name,created_at) "
        "SELECT id,1,'stage','2026-09-14T00:00:00Z' FROM sites "
        "WHERE project_id=1 ORDER BY id LIMIT 1 "
        "ON CONFLICT(project_id,name) DO NOTHING"
    )
    conn.commit()


def _flow(conn: Any, flow_id: str, *, advanced: bool) -> None:
    stages = (
        ADVANCED_STAGES
        if advanced
        else json.dumps([{"name": "deploy", "step_runner": "auto"}])
    )
    cmd_create(
        conn,
        flow_id,
        "yoke",
        flow_id,
        "",
        stages,
        status="disabled" if advanced else "active",
    )


def _run(conn: Any, run_id: str, flow_id: str, *, lineage: str) -> None:
    conn.execute(
        "INSERT INTO deployment_runs("
        "id,project_id,flow,release_lineage,status,created_at,"
        "composition_resolution) VALUES (%s,1,%s,%s,'created',%s,%s)",
        (
            run_id,
            flow_id,
            lineage,
            "2026-09-14T00:00:00Z",
            "operator confirmed the first governed composition baseline",
        ),
    )
    conn.commit()


def _plan(conn: Any, plan_id: int) -> None:
    conn.execute(
        "INSERT INTO qa_plans(id,project_id,slug,name,description,created_at,updated_at) "
        "VALUES (%s,1,%s,%s,'',%s,%s)",
        (
            plan_id,
            f"release-plan-{plan_id}",
            "Release plan",
            "2026-09-14T00:00:00Z",
            "2026-09-14T00:00:00Z",
        ),
    )
    conn.execute(
        "INSERT INTO qa_plan_cases(plan_id,case_key,position,method_id,instructions,"
        "expected_outcome,created_at,updated_at) VALUES "
        "(%s,'smoke',1,'command','run original smoke','passes',%s,%s)",
        (plan_id, "2026-09-14T00:00:00Z", "2026-09-14T00:00:00Z"),
    )
    conn.commit()


def _flow_with_plan(conn: Any, flow_id: str, plan_id: int) -> None:
    stages = json.loads(ADVANCED_STAGES)
    stages[1]["cases"] = {"plan_id": plan_id, "case_keys": ["smoke"]}
    cmd_create(
        conn,
        flow_id,
        "yoke",
        flow_id,
        "",
        json.dumps(stages),
        status="disabled",
    )


def _known_carried(item_id: int) -> dict[str, Any]:
    return {
        "schema": 1,
        "derivation": {"contents_known": True, "reason": "test-fixture"},
        "items": [{"item_id": item_id, "ref": f"YOK-{item_id}", "commit_shas": []}],
        "commits": [],
    }


def test_legacy_run_and_empty_environment_run_skip_new_admission(
    test_db: Any,
) -> None:
    _flow(test_db, "legacy-flow", advanced=False)
    _run(test_db, "run-legacy", "legacy-flow", lineage="main")
    assert composition.freeze_run_composition(test_db, "run-legacy") == {
        "run_id": "run-legacy",
        "frozen_at": "",
        "legacy": True,
    }


def test_release_policy_requires_a_resolved_commit_before_freeze(
    test_db: Any,
) -> None:
    _environment(test_db)
    _flow(test_db, "advanced-moving", advanced=True)
    _run(test_db, "run-moving", "advanced-moving", lineage="origin/main")
    with pytest.raises(ValueError, match="resolved full 40-hex commit"):
        composition.freeze_run_composition(test_db, "run-moving")


def test_repeated_blitz_membership_freezes_explicit_requirements_and_intent(
    test_db: Any,
    monkeypatch,
) -> None:
    _environment(test_db)
    _flow(test_db, "advanced-blitz", advanced=True)
    insert_item(
        test_db,
        id=9311,
        project_sequence=9311,
        workflow_id="blitz",
        status="implementing",
        deployment_flow="advanced-blitz",
    )
    first = insert_qa_requirement(
        test_db,
        item_id=9311,
        qa_kind="browser",
        qa_phase="post_deploy",
        instructions="capture the delivered slice",
    )
    second = insert_qa_requirement(
        test_db,
        item_id=9311,
        qa_kind="command",
        qa_phase="post_deploy",
        instructions="verify the final document",
    )
    first_id = int(first["id"])
    second_id = int(second["id"])
    monkeypatch.setattr(
        composition, "record_carried_work", lambda _conn, _run: _known_carried(9311)
    )

    _run(test_db, "run-progress", "advanced-blitz", lineage="a" * 40)
    cmd_add_item("run-progress", 9311, requirement_ids=[first_id])
    composition.freeze_run_composition(test_db, "run-progress")
    progress = test_db.execute(
        "SELECT delivery_intent,requirement_snapshot FROM deployment_run_items "
        "WHERE run_id='run-progress' AND item_id=9311"
    ).fetchone()
    progress_snapshot = json.loads(progress["requirement_snapshot"])
    assert progress["delivery_intent"] == "progress"
    assert [row["id"] for row in progress_snapshot["requirements"]] == [first_id]
    assert (
        test_db.execute(
            "SELECT artifact_identity FROM deployment_runs WHERE id='run-progress'"
        ).fetchone()[0]
        is None
    )

    test_db.execute("UPDATE items SET status='release' WHERE id=9311")
    test_db.commit()
    _run(test_db, "run-final", "advanced-blitz", lineage="b" * 40)
    cmd_add_item("run-final", 9311, requirement_ids=[second_id])
    composition.freeze_run_composition(test_db, "run-final")
    final = test_db.execute(
        "SELECT delivery_intent,requirement_snapshot FROM deployment_run_items "
        "WHERE run_id='run-final' AND item_id=9311"
    ).fetchone()
    assert final["delivery_intent"] == "final"
    assert [
        row["id"] for row in json.loads(final["requirement_snapshot"])["requirements"]
    ] == [second_id]

    assert cmd_update("run-progress", "status", "cancelled") is None
    retained = test_db.execute(
        "SELECT requirement_snapshot FROM deployment_run_items "
        "WHERE run_id='run-progress' AND item_id=9311"
    ).fetchone()
    assert retained["requirement_snapshot"] == progress["requirement_snapshot"]


def test_plan_content_and_candidate_stay_frozen_across_cancel_and_retry(
    test_db: Any,
    monkeypatch,
) -> None:
    _environment(test_db)
    _plan(test_db, 9411)
    _flow_with_plan(test_db, "advanced-plan", 9411)
    insert_item(
        test_db,
        id=9412,
        project_sequence=141,
        workflow_id="blitz",
        status="implementing",
        deployment_flow="advanced-plan",
    )
    test_db.execute(
        "INSERT INTO qa_plan_item_attachments"
        "(item_id,transition_id,qa_phase,plan_id,attached_at) "
        "VALUES (9412,'implemented','verification',9411,%s)",
        ("2026-09-14T00:00:00Z",),
    )
    test_db.commit()
    monkeypatch.setattr(
        composition, "record_carried_work", lambda _conn, _run: _known_carried(9412)
    )

    _run(test_db, "run-plan", "advanced-plan", lineage="c" * 40)
    assert cmd_update("run-plan", "artifact_identity", "artifact-original") is None
    cmd_add_item("run-plan", 9412, plan_ids=[9411])
    assert cmd_update("run-plan", "status", "executing") is None
    frozen = test_db.execute(
        "SELECT requirement_snapshot,artifact_identity FROM deployment_runs "
        "WHERE id='run-plan'"
    ).fetchone()
    member = test_db.execute(
        "SELECT requirement_snapshot FROM deployment_run_items "
        "WHERE run_id='run-plan' AND item_id=9412"
    ).fetchone()
    test_db.execute("UPDATE qa_plans SET name='Mutated plan' WHERE id=9411")
    test_db.execute(
        "UPDATE qa_plan_cases SET instructions='mutated smoke' WHERE plan_id=9411"
    )
    test_db.commit()
    repeated = composition.freeze_run_composition(test_db, "run-plan")
    assert repeated["frozen_at"]
    assert frozen["artifact_identity"] == "artifact-original"
    frozen_flow = json.loads(frozen["requirement_snapshot"])
    assert frozen_flow["selections"][0]["plan"]["name"] == "Release plan"
    assert "created_at" not in frozen_flow["selections"][0]["plan"]
    assert (
        json.loads(member["requirement_snapshot"])["plans"][0]["cases"][0][
            "instructions"
        ]
        == "run original smoke"
    )
    assert "frozen composition" in str(
        cmd_update("run-plan", "artifact_identity", "artifact-mutated")
    )
    assert "frozen composition" in str(
        cmd_update("run-plan", "release_lineage", "e" * 40)
    )
    with pytest.raises(ValueError, match="membership is mutable only"):
        cmd_remove_item("run-plan", 9412)
    assert cmd_update("run-plan", "status", "cancelled") is None
    with pytest.raises(ValueError, match="membership is mutable only"):
        cmd_add_item("run-plan", 9412)

    _run(test_db, "run-plan-retry", "advanced-plan", lineage="d" * 40)
    cmd_add_item("run-plan-retry", 9412, plan_ids=[9411])
    assert cmd_update("run-plan-retry", "status", "executing") is None
    retry = test_db.execute(
        "SELECT requirement_snapshot FROM deployment_runs WHERE id='run-plan-retry'"
    ).fetchone()
    assert (
        json.loads(retry["requirement_snapshot"])["selections"][0]["plan"]["name"]
        == "Mutated plan"
    )
    assert (
        test_db.execute(
            "SELECT requirement_snapshot FROM deployment_runs WHERE id='run-plan'"
        ).fetchone()[0]
        == frozen["requirement_snapshot"]
    )


def test_membership_classification_is_terminal_and_default_safe(test_db: Any) -> None:
    _flow(test_db, "effective-default", advanced=False)
    insert_item(
        test_db,
        id=9321,
        project_sequence=9321,
        workflow_id="blitz",
        status="implementing",
    )
    insert_item(
        test_db,
        id=9322,
        project_sequence=9322,
        workflow_id="dash",
        status="done",
        deployment_flow="effective-default",
    )
    insert_item(
        test_db,
        id=9323,
        project_sequence=9323,
        workflow_id="task",
        status="implementing",
    )
    set_delivery_default(
        test_db, project="yoke", workflow_id="blitz", flow_id="effective-default"
    )
    set_delivery_default(
        test_db, project="yoke", workflow_id="task", flow_id="effective-default"
    )
    assert composition._item_requires_release_membership(test_db, 9321)
    assert not composition._item_requires_release_membership(test_db, 9322)
    assert not composition._item_requires_release_membership(test_db, 9323)
