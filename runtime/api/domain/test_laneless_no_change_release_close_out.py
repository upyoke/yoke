"""A laneless no-change Dash finishes its release wait on its own evidence.

The done nonce proves a close-out that merges and cleans up; a Dash that
recorded a no-change finding and never opened a lane has neither to do, so
its lifecycle transition is the ceremony. Every other done gate still runs.
"""

from __future__ import annotations

from runtime.api.domain.test_dash_posture_deployment_containment import (  # noqa: F401
    _insert_dash,
    dash_db_path,
)
from runtime.api.domain.test_no_change_dash_close_out import (
    _bind_fixture_db,
    _empty_delivery_reads,
    _request,
)
from runtime.api.domain.test_status_transition_preflight import (
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
        test_db, id=item_id, workflow_id="dash", status="implementing",
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
            conn, id="run-no-change", flow="flow-test", status="succeeded",
            release_lineage="f" * 40,
        )
        conn.execute(
            "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
            "VALUES ('run-no-change', 8701, '2026-01-01T00:00:00Z')"
        )
        conn.commit()
        delivered = evaluate(
            item_id=8701, target_status="done", db_path=dash_db_path
        )
    finally:
        conn.close()

    assert held is not None
    assert held["error_code"] == "GATE_DASH_DEPLOYMENT_REQUIRED"
    assert delivered is None
