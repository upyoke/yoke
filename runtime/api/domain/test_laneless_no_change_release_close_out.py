# ruff: noqa: F811
"""A laneless no-change Dash finishes its release wait on its own evidence.

The done nonce proves a close-out that merges and cleans up; a Dash that
recorded a no-change finding and never opened a lane has neither to do, so
its lifecycle transition is the ceremony. Every other done gate still runs.
"""

from __future__ import annotations

import json

from runtime.api.domain.dash_posture_deployment_containment_test_support import (dash_db_path as dash_db_path)

from runtime.api.domain.dash_posture_deployment_containment_test_support import (
    _insert_dash,
)
from runtime.api.domain.no_change_dash_close_out_test_support import (
    _bind_fixture_db,
    _empty_delivery_reads,
    _request,
)
from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)
from runtime.api.fixtures.backlog_inserts import (
    insert_deployment_run,
    insert_item,
    insert_item_worktree,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.fixtures.session_holdings import insert_item_claim, insert_session
from yoke_core.domain.dash_execution import record_dash_evidence
from yoke_core.domain.dash_posture_gate import evaluate
from yoke_core.domain.handlers.direct_workflow_execution import (
    handle_dash_evidence,
    handle_dash_survey,
)
from yoke_core.domain.handlers.lifecycle_transition import handle_transition


def _no_change_evidence(item_id: int) -> dict:
    return {
        "result_summary": "No code change was required.",
        "verification_summary": "Observed the behaviour already holds.",
        "verification_status": "passed",
        "commit_sha": "",
        "merge_sha": "",
        "touched_files": [],
        "tree_root": "",
        "tree_head_sha": "",
        "no_changes": True,
    }


def _at_release_wait(test_db, monkeypatch, *, item_id: int, session_id: str) -> str:
    _isolate_status_effects(monkeypatch)
    _bind_fixture_db(monkeypatch, test_db)
    _empty_delivery_reads(monkeypatch)
    actor_id = str(
        test_db.execute(
            "SELECT id FROM actors WHERE kind='human' ORDER BY id LIMIT 1"
        ).fetchone()[0]
    )
    insert_item(
        test_db,
        id=item_id,
        workflow_id="dash",
        status="implementing",
        title="Laneless no-change release",
    )
    insert_session(test_db, session_id)
    insert_item_claim(test_db, session_id, item_id)
    ask = dict(actor_id=actor_id, item_id=item_id, session_id=session_id)
    assert handle_dash_survey(
        _request(
            "direct_workflow.dash.survey",
            {"paths": [], "path_sizes": [], "no_changes": True},
            **ask,
        )
    ).primary_success
    assert handle_dash_evidence(
        _request("direct_workflow.dash.evidence", _no_change_evidence(item_id), **ask)
    ).primary_success
    for source, target in (
        ("implementing", "reviewing-implementation"),
        ("reviewing-implementation", "release"),
    ):
        outcome = handle_transition(
            _request(
                "lifecycle.transition.execute",
                {"source_status": source, "target_status": target},
                **ask,
            )
        )
        assert outcome.primary_success is True, outcome.error
    return actor_id


def _close(test_db, *, item_id: int, session_id: str, actor_id: str):
    return handle_transition(
        _request(
            "lifecycle.transition.execute",
            {"source_status": "release", "target_status": "done"},
            actor_id=actor_id,
            item_id=item_id,
            session_id=session_id,
        )
    )


def test_absent_worktree_without_no_changes_evidence_is_not_laneless():
    from yoke_core.domain.dash_execution import proved_laneless_no_change

    assert (
        proved_laneless_no_change(
            workflow_id="dash", no_changes=False, active_worktree_present=False
        )
        is False
    )
    assert (
        proved_laneless_no_change(
            workflow_id="dash", no_changes=True, active_worktree_present=False
        )
        is True
    )
    assert (
        proved_laneless_no_change(
            workflow_id="dash", no_changes=True, active_worktree_present=True
        )
        is False
    )
    assert (
        proved_laneless_no_change(
            workflow_id="task", no_changes=True, active_worktree_present=False
        )
        is False
    )


def test_laneless_no_change_dash_closes_its_release_wait(test_db, monkeypatch):
    actor = _at_release_wait(test_db, monkeypatch, item_id=7120, session_id="ll-a")

    outcome = _close(test_db, item_id=7120, session_id="ll-a", actor_id=actor)

    assert outcome.primary_success is True, outcome.error
    status = test_db.execute("SELECT status FROM items WHERE id=7120").fetchone()
    assert status[0] == "done"


def test_a_no_change_dash_with_a_lane_still_needs_the_merge_close_out(
    test_db, monkeypatch
):
    actor = _at_release_wait(test_db, monkeypatch, item_id=7121, session_id="ll-b")
    insert_item_worktree(test_db, item_id=7121, branch="lane-7121")

    outcome = _close(test_db, item_id=7121, session_id="ll-b", actor_id=actor)

    assert outcome.primary_success is False
    assert "ceremony nonce" in outcome.error.message
    status = test_db.execute("SELECT status FROM items WHERE id=7121").fetchone()
    assert status[0] == "release"


def _record_no_change(conn, item_id: int) -> None:
    record_dash_evidence(conn, item_id=item_id, **_no_change_evidence(item_id))


def test_deployment_posture_holds_a_no_change_member_until_its_run_succeeds(
    dash_db_path,
):
    conn = connect_test_db(dash_db_path)
    try:
        _insert_dash(conn, item_id=8701, posture={"deployment": True})
        _record_no_change(conn, 8701)
        conn.commit()
        held = evaluate(item_id=8701, target_status="done", db_path=dash_db_path)
        insert_deployment_run(
            conn,
            id="run-no-change",
            flow="flow-test",
            status="succeeded",
            release_lineage="f" * 40,
        )
        conn.execute(
            "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
            "VALUES ('run-no-change', 8701, '2026-01-01T00:00:00Z')"
        )
        conn.commit()
        delivered = evaluate(item_id=8701, target_status="done", db_path=dash_db_path)
    finally:
        conn.close()

    assert held is not None
    assert held["error_code"] == "GATE_DASH_DEPLOYMENT_REQUIRED"
    assert delivered is None


def _select_deployment(conn, item_id: int, flow: str) -> None:
    conn.execute(
        "UPDATE items SET deployment_flow=%s, workflow_posture=%s WHERE id=%s",
        (flow, '{"deployment": true}', item_id),
    )
    conn.commit()


def _assert_missing_membership(conn, item_id, command):
    from yoke_core.domain.next_actor import item_next_actor
    from yoke_core.domain.next_actor_facts import next_actor_facts

    held = evaluate(item_id=item_id, target_status="done", db_path="")
    assert held["error_code"] == "GATE_DASH_DEPLOYMENT_REQUIRED"
    assert "No completion run lists" in held["error"]
    assert command in held["remediation_hint"]
    _, items = next_actor_facts(conn, item_ids=(item_id,))
    next_actor = item_next_actor(items[item_id])
    assert next_actor["reason"] == "release_membership_required"
    assert next_actor["recovery"] == held["remediation_hint"]
    assert held["error"] in next_actor["sentence"]


def test_no_change_dash_is_enrolled_by_the_next_release_run(
    test_db, monkeypatch, tmp_path
):
    from runtime.api.domain.no_obligation_member_close_out_test_support import _no_obligation
    from runtime.api.fixtures.carried_release_candidate import (
        release_repository,
        serve_repository,
        stage_environment,
    )
    from yoke_core.domain.deployment_run_create_write import create_run
    from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
    from yoke_core.domain.flow_create import cmd_create
    from yoke_core.domain.project_identity import render_item_ref

    item_id, session_id = 7122, "ll-c"
    actor = _at_release_wait(
        test_db, monkeypatch, item_id=item_id, session_id=session_id
    )
    flow = "no-change-release-flow"
    stage_environment(test_db)
    cmd_create(
        test_db,
        flow,
        "yoke",
        "Release with no changes",
        "",
        json.dumps(
            [
                {
                    "name": "deploy",
                    "step_runner": "auto",
                    "stage_kind": "execution",
                    "scope": "run",
                }
            ]
        ),
        target_tier="persistent",
        environment="stage",
    )
    _select_deployment(test_db, item_id, flow)
    _assert_missing_membership(
        test_db, item_id, f"yoke deployment-runs create yoke {flow}"
    )
    assert not _close(
        test_db, item_id=item_id, session_id=session_id, actor_id=actor
    ).primary_success

    provisional = "run-open"
    insert_deployment_run(test_db, id=provisional, flow=flow)
    ref = render_item_ref(test_db, item_id)
    _assert_missing_membership(
        test_db, item_id, f"yoke deployment-runs add-item {provisional} {ref}"
    )
    test_db.execute(
        "UPDATE deployment_runs SET status='cancelled' WHERE id=%s", (provisional,)
    )
    test_db.commit()

    someone_else = 7123
    insert_item(
        test_db,
        id=someone_else,
        workflow_id="dash",
        status="release",
        title="Other flow",
    )
    _record_no_change(test_db, someone_else)
    _select_deployment(test_db, someone_else, "different-flow")

    repo, _, tip = release_repository(tmp_path, ref)
    serve_repository(monkeypatch, repo)
    _no_obligation(test_db, item_id, reason="No post-deploy validation is owed.")
    test_db.commit()
    run = create_run("yoke", flow, release_lineage=tip)
    members = test_db.execute(
        "SELECT item_id FROM deployment_run_items WHERE run_id=%s", (run.run_id,)
    ).fetchall()
    assert [row[0] for row in members] == [item_id]
    assert evaluate(item_id=item_id, target_status="done", db_path="") is not None

    test_db.execute(
        "UPDATE deployment_runs SET status='executing', current_stage='deploy' WHERE id=%s",
        (run.run_id,),
    )
    test_db.commit()
    refusal = cmd_update(run.run_id, "status", "succeeded")
    assert refusal is None, refusal
    assert (
        test_db.execute("SELECT status FROM items WHERE id=%s", (item_id,)).fetchone()[
            0
        ]
        == "done"
    )
