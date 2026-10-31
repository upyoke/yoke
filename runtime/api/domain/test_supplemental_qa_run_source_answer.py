"""A supplemental QA run answers its environment while it still executes.

One release runs a stage QA run beside the production run that delivers the
item. When the stage member's item QA is accepted before either run reaches
``succeeded``, the stage source is answered by that accepted QA: the stage run
never delivers, so asking whether it is the item's completion run can never
say yes.
"""

from runtime.api.domain.test_dash_post_deploy_done_consumption import _accept_member_qa
from runtime.api.domain.test_release_member_target_enrollment import _pair
from yoke_core.domain.deployment_member_independent_close_out import (
    independent_member_delivery_ready,
    member_qa_answer_ready,
)
from yoke_core.domain.deployment_qa_source_obligation import source_obligation_consumed
from yoke_core.domain.deployment_run_member_targeting import supplemental_qa_run
from yoke_core.domain.qa_gate_definitions import GateTarget
from yoke_core.domain.qa_gate_summary import render_gate_summary


def _final_members(conn, *, item_id):
    conn.execute(
        "UPDATE deployment_run_items SET delivery_intent='final' WHERE item_id=%s",
        (item_id,),
    )
    conn.commit()


def _executing(conn, run_id):
    conn.execute("UPDATE deployment_runs SET status='executing' WHERE id=%s", (run_id,))
    conn.commit()


def test_executing_stage_run_answers_stage_source_beside_executing_prod(test_db, tmp_path, monkeypatch):
    item_id = 9691
    sources = _pair(test_db, item_id=item_id)
    from runtime.api.fixtures.supplemental_credit import topology, pin

    commits = topology(test_db, tmp_path, monkeypatch, item_id)
    for run_id in ("run-prod", "run-stage"):
        pin(test_db, run_id, commits["landing"])
    _final_members(test_db, item_id=item_id)
    assert supplemental_qa_run(test_db, run_id="run-stage", item_id=item_id)
    _accept_member_qa(test_db, run_id="run-stage", item_id=item_id)
    _executing(test_db, "run-stage")

    # The stage run is not the item's delivery, so the delivery reader says no.
    assert not independent_member_delivery_ready(
        test_db, item_id=item_id, run_id="run-stage"
    )
    assert member_qa_answer_ready(test_db, item_id=item_id, run_id="run-stage")
    assert source_obligation_consumed(
        test_db, item_id=item_id, source_requirement_id=sources["stage"]
    )
    # Production still owes its own proof.
    assert not source_obligation_consumed(
        test_db, item_id=item_id, source_requirement_id=sources["prod"]
    )
    # The diagnostic a failed close-out names reads the same answer.
    summary = render_gate_summary(
        GateTarget(item_id=item_id),
        str(test_db.info.dsn),
        transition_name="implemented",
    )
    satisfied = {row["id"]: row["satisfied"] for row in summary["requirements"]}
    assert satisfied[sources["stage"]] is True
    assert satisfied[sources["prod"]] is False


def test_unaccepted_executing_stage_run_does_not_answer(test_db):
    item_id = 9692
    sources = _pair(test_db, item_id=item_id)
    _final_members(test_db, item_id=item_id)
    assert not member_qa_answer_ready(test_db, item_id=item_id, run_id="run-stage")
    assert not source_obligation_consumed(
        test_db, item_id=item_id, source_requirement_id=sources["stage"]
    )


def test_progress_member_on_stage_run_does_not_answer_early(test_db):
    item_id = 9693
    sources = _pair(test_db, item_id=item_id)
    _accept_member_qa(test_db, run_id="run-stage", item_id=item_id)
    _executing(test_db, "run-stage")
    assert not member_qa_answer_ready(test_db, item_id=item_id, run_id="run-stage")
    assert not source_obligation_consumed(
        test_db, item_id=item_id, source_requirement_id=sources["stage"]
    )
