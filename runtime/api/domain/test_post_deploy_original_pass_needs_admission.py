"""A post_deploy row's own passing run does not close the item out.

That run was recorded against whatever candidate was deployed when it ran, so
honouring it at ``done`` lets a prior candidate's proof close out the release
actually being delivered -- the substitution frozen admission exists to
prevent. Every done-gate consumer therefore judges a ``post_deploy`` row on
the completion run's admitted copy even when the original row has passed: the
Dash posture gate, the shared blocking-requirement gate the authoritative
status gate reads, and the blocking count the status write itself computes.

Phases that are not ``post_deploy`` keep their established meaning, where the
original row's own passing run is the satisfaction.
"""

from __future__ import annotations

import pytest

from runtime.api.domain.test_dash_post_deploy_done_consumption import (
    _accept_member_qa,
    _bind_original,
    _retarget_run,
    _transition_done,
)
from runtime.api.domain.test_dash_post_deploy_review_isolation import _insert_dash
from runtime.api.domain.test_deployment_qa_admission_execution import (
    _seed_selected_requirement_run,
)
from runtime.api.fixtures.backlog_inserts import insert_qa_run
from yoke_core.domain import delivery_evidence_ladder as ladder
from yoke_core.domain.dash_execution import record_dash_evidence
from yoke_core.domain.dash_posture_gate import evaluate
from yoke_core.domain.deployment_run_candidate_containment import (
    CONTAINED,
    NOT_CONTAINED,
    ContainmentVerdict,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_source_obligation import source_obligation_consumed
from yoke_core.domain.delivery_evidence_ladder import delivery_evidence
from yoke_core.domain.item_merge_receipt_document import record_entry
from yoke_core.domain.qa_gates import GateTarget, check_done_gate


def _record_evidence(conn, *, item_id: int) -> None:
    record_dash_evidence(
        conn,
        item_id=item_id,
        result_summary="Merged the Dash.",
        verification_summary="Focused checks passed.",
        verification_status="passed",
        commit_sha="e" * 40,
        merge_sha="d" * 40,
        touched_files=["ui/dash.js"],
        tree_root="/repo/.worktrees/lane",
        tree_head_sha="abc1234",
    )


def _assert_every_done_consumer_refuses(conn, *, item_id: int, source_id: int) -> None:
    """Each consumer refuses, and each names a recovery that can actually
    clear the row. "Execute the case" cannot: the row may already have a
    passing run, and running it again records another one against the same
    unchanged candidate."""
    db_path = str(conn.info.dsn)
    blocked = evaluate(item_id=item_id, target_status="done", db_path=db_path)
    assert blocked is not None
    assert blocked["error_code"] == "GATE_DASH_VERIFICATION_UNSATISFIED"
    assert str(source_id) in blocked["error"]
    assert "registered QA case runner" not in blocked["remediation_hint"]
    _assert_teaches_the_way_out(blocked["remediation_hint"])

    shared = check_done_gate(GateTarget(item_id=item_id), db_path)
    assert shared.passed is False
    assert any(f"#{source_id}" in error for error in shared.errors)
    assert any("not accepted on the completion run" in e for e in shared.errors)
    _assert_teaches_the_way_out("\n".join(shared.errors))


def _assert_teaches_the_way_out(text: str) -> None:
    assert "admitted" in text
    assert "target_env" in text
    assert "waive" in text
    assert "permanently" not in text


def test_an_original_pass_without_any_completion_run_still_blocks_done(
    test_db,
    monkeypatch: pytest.MonkeyPatch,
):
    """The plainest shape of the substitution: the source passed once, against
    a deployment this item no longer has any run for at all."""
    item_id = 2340
    _insert_dash(test_db, item_id=item_id, status="release")
    source_id = _bind_original(test_db, item_id=item_id)
    insert_qa_run(test_db, qa_requirement_id=source_id, verdict="pass")
    _record_evidence(test_db, item_id=item_id)

    _assert_every_done_consumer_refuses(test_db, item_id=item_id, source_id=source_id)
    outcome = _transition_done(test_db, item_id=item_id, monkeypatch=monkeypatch)
    assert outcome.primary_success is False
    # The status write refuses before the shared gate runs, so its own
    # message is the one an operator reads first and must carry the recovery.
    _assert_teaches_the_way_out(outcome.error.message)
    status = test_db.execute(
        "SELECT status FROM items WHERE id=%s", (item_id,)
    ).fetchone()[0]
    assert status == "release"


def test_an_original_pass_does_not_survive_a_rejected_admitted_copy(
    test_db,
    monkeypatch: pytest.MonkeyPatch,
):
    item_id = 2341
    _insert_dash(test_db, item_id=item_id, status="release")
    source_id = _bind_original(test_db, item_id=item_id)
    insert_qa_run(test_db, qa_requirement_id=source_id, verdict="pass")
    _seed_selected_requirement_run(
        test_db,
        run_id="run-rejected-copy",
        item_id=item_id,
        requirement_id=source_id,
    )
    created = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-rejected-copy",
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
    )
    copy_id = int(created["created_requirement_ids"][0])
    insert_qa_run(test_db, qa_requirement_id=copy_id, verdict="fail")
    test_db.execute(
        "UPDATE deployment_runs SET status='succeeded' WHERE id=%s",
        ("run-rejected-copy",),
    )
    test_db.commit()
    _record_evidence(test_db, item_id=item_id)

    _assert_every_done_consumer_refuses(test_db, item_id=item_id, source_id=source_id)
    outcome = _transition_done(test_db, item_id=item_id, monkeypatch=monkeypatch)
    assert outcome.primary_success is False


def test_an_original_pass_does_not_survive_a_stale_accepted_copy(
    test_db,
    monkeypatch: pytest.MonkeyPatch,
):
    """An earlier run accepted this source and a newer run has not. The
    completion run is the latest one, so the accepted copy is not its."""
    item_id = 2342
    _insert_dash(test_db, item_id=item_id, status="release")
    source_id = _bind_original(test_db, item_id=item_id)
    insert_qa_run(test_db, qa_requirement_id=source_id, verdict="pass")
    _seed_selected_requirement_run(
        test_db,
        run_id="run-earlier-accepted",
        item_id=item_id,
        requirement_id=source_id,
    )
    _accept_member_qa(test_db, run_id="run-earlier-accepted", item_id=item_id)
    _seed_selected_requirement_run(
        test_db,
        run_id="run-latest-pending",
        item_id=item_id,
        requirement_id=source_id,
    )
    _retarget_run(
        test_db,
        run_id="run-latest-pending",
        lineage="d" * 40,
        created_at="2026-09-14T00:10:00Z",
    )
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id="run-latest-pending",
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
    )
    _record_evidence(test_db, item_id=item_id)

    _assert_every_done_consumer_refuses(test_db, item_id=item_id, source_id=source_id)
    outcome = _transition_done(test_db, item_id=item_id, monkeypatch=monkeypatch)
    assert outcome.primary_success is False


def test_an_accepted_admitted_copy_closes_out_a_source_that_also_passed(
    test_db,
    monkeypatch: pytest.MonkeyPatch,
):
    """The valid shape: the completion run admitted and accepted this source.
    The original row's own pass neither helps nor hinders, and the original is
    still not re-run and not waived."""
    item_id = 2343
    _insert_dash(test_db, item_id=item_id, status="release")
    source_id = _bind_original(test_db, item_id=item_id)
    insert_qa_run(test_db, qa_requirement_id=source_id, verdict="pass")
    _seed_selected_requirement_run(
        test_db,
        run_id="run-accepted-copy",
        item_id=item_id,
        requirement_id=source_id,
    )
    _accept_member_qa(test_db, run_id="run-accepted-copy", item_id=item_id)
    _record_evidence(test_db, item_id=item_id)

    db_path = str(test_db.info.dsn)
    assert evaluate(item_id=item_id, target_status="done", db_path=db_path) is None
    assert check_done_gate(GateTarget(item_id=item_id), db_path).passed is True
    outcome = _transition_done(test_db, item_id=item_id, monkeypatch=monkeypatch)
    assert outcome.primary_success is True, outcome.error
    status = test_db.execute(
        "SELECT status FROM items WHERE id=%s", (item_id,)
    ).fetchone()[0]
    original_runs = test_db.execute(
        "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id=%s AND verdict='pass'",
        (source_id,),
    ).fetchone()[0]
    waived = test_db.execute(
        "SELECT waived_at FROM qa_requirements WHERE id=%s", (source_id,)
    ).fetchone()[0]
    assert status == "done"
    assert int(original_runs) == 1
    assert waived is None


def test_cancelled_newer_run_does_not_mask_the_delivered_qa(
    test_db,
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(
        ladder,
        "candidate_contains_commit",
        lambda _conn, _project, *, candidate_lineage, commit_sha: ContainmentVerdict(
            CONTAINED if candidate_lineage == commit_sha else NOT_CONTAINED
        ),
    )
    item_id = 2345
    _insert_dash(test_db, item_id=item_id, status="release")
    source_id = _bind_original(test_db, item_id=item_id)
    _seed_selected_requirement_run(
        test_db,
        run_id="run-delivered",
        item_id=item_id,
        requirement_id=source_id,
    )
    _retarget_run(
        test_db,
        run_id="run-delivered",
        lineage="d" * 40,
        created_at="2026-09-14T00:00:00Z",
    )
    _accept_member_qa(test_db, run_id="run-delivered", item_id=item_id)
    _seed_selected_requirement_run(
        test_db,
        run_id="run-cancelled",
        item_id=item_id,
        requirement_id=source_id,
    )
    _retarget_run(
        test_db,
        run_id="run-cancelled",
        lineage="d" * 40,
        created_at="2026-09-14T00:10:00Z",
    )
    test_db.execute(
        "UPDATE deployment_runs SET flow=%s,status='cancelled' WHERE id=%s",
        ("flow-run-delivered", "run-cancelled"),
    )
    test_db.execute(
        "UPDATE items SET deployment_flow=%s WHERE id=%s",
        ("flow-run-delivered", item_id),
    )
    test_db.commit()
    _record_evidence(test_db, item_id=item_id)
    record_entry(
        test_db,
        item_id=item_id,
        branch="test-lane",
        target="main",
        merge_sha="d" * 40,
    )
    # A later successful release contains the same merge, but did not enroll
    # this item and therefore has no admitted copy of its source requirement.
    test_db.execute(
        "INSERT INTO deployment_runs "
        "(id,project_id,flow,status,release_lineage,created_at,completed_at) "
        "SELECT %s,project_id,flow,'succeeded',%s,%s,%s "
        "FROM deployment_runs WHERE id=%s",
        (
            "run-containing-without-member",
            "d" * 40,
            "2026-09-14T00:20:00Z",
            "2026-09-14T00:21:00Z",
            "run-delivered",
        ),
    )
    test_db.commit()

    delivered = delivery_evidence(test_db, item_id)
    assert delivered.discharged, delivered
    # The cancelled run does not shadow the item's own delivered membership,
    # so membership answers before the later containing release is consulted.
    assert delivered.run_id == "run-delivered"
    assert source_obligation_consumed(
        test_db, item_id=item_id, source_requirement_id=source_id
    )
    db_path = str(test_db.info.dsn)
    assert evaluate(item_id=item_id, target_status="done", db_path=db_path) is None
    assert check_done_gate(GateTarget(item_id=item_id), db_path).passed is True
    outcome = _transition_done(test_db, item_id=item_id, monkeypatch=monkeypatch)
    assert outcome.primary_success is True, outcome.error


def test_a_verification_row_is_still_satisfied_by_its_own_passing_run(
    test_db,
    monkeypatch: pytest.MonkeyPatch,
):
    """Only post_deploy is answered by the completion run. A verification-phase
    row proves the branch and closes out on its own pass, with no deployment
    run anywhere."""
    item_id = 2344
    _insert_dash(test_db, item_id=item_id, status="release")
    source_id = _bind_original(test_db, item_id=item_id)
    test_db.execute(
        "UPDATE qa_requirements SET qa_phase='verification' WHERE id=%s",
        (source_id,),
    )
    test_db.commit()
    insert_qa_run(test_db, qa_requirement_id=source_id, verdict="pass")
    _record_evidence(test_db, item_id=item_id)

    db_path = str(test_db.info.dsn)
    assert evaluate(item_id=item_id, target_status="done", db_path=db_path) is None
    assert check_done_gate(GateTarget(item_id=item_id), db_path).passed is True
    outcome = _transition_done(test_db, item_id=item_id, monkeypatch=monkeypatch)
    assert outcome.primary_success is True, outcome.error
