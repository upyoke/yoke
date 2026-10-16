"""Release diagnostics retain item closure debt outside run-bound QA counts."""

from dataclasses import replace

from runtime.api.domain.test_deployment_delivery_close_out_notice import _project
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import HOLDER_A, HOLDER_B
from runtime.api.domain.test_no_obligation_member_close_out import (
    _ready_member,
    _no_obligation,
)
from runtime.api.domain.test_run_success_member_settlement import (
    _executing_run,
    _status,
)
from runtime.api.fixtures.backlog_inserts import insert_qa_requirement
from runtime.api.steering_fleet_test_helpers import NOW
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain import delivery_member_close_steps
from yoke_core.domain.deployment_run_completion_preview import (
    completion_preview,
    run_completion_diagnostics,
)
from yoke_core.domain.deployment_run_completion_preconditions import (
    unresolved_blocking_qa,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.steering_fleet_report_deployment_runs import run_progress
from yoke_core.domain.steering_fleet_report_projection import _run_dict
from yoke_core.domain.steering_fleet_report_render import _run_lines

RUN = "run-member-debt"
FIRST, SECOND = 9891, 9892


def _seed(conn, *, required=True, answer_first=True):
    _project(conn)
    for item_id, holder in ((FIRST, HOLDER_A), (SECOND, HOLDER_B)):
        _ready_member(conn, item_id, holder)
        if item_id != FIRST or answer_first:
            _no_obligation(conn, item_id, reason="nothing observable once deployed")
    _executing_run(conn, RUN, (FIRST, SECOND))
    requirement = insert_qa_requirement(
        conn,
        item_id=SECOND,
        qa_kind="command",
        qa_phase="manual_acceptance",
        target_env="stage",
    )
    if required:
        insert_qa_requirement(
            conn, item_id=SECOND, qa_phase="verification", target_env="prod"
        )
    conn.execute(
        "UPDATE deployment_runs SET settling_at=%s,current_stage='complete' WHERE id=%s",
        (NOW, RUN),
    )
    conn.commit()
    return int(requirement["id"])


def test_other_target_requirement_and_atomic_sibling_are_current_read_facts(
    test_db, monkeypatch
):
    requirement_id = _seed(test_db)
    status = _status(test_db, FIRST)

    def no_close(*args, **kwargs):
        raise AssertionError("a report must never prepare or stage close-out")

    monkeypatch.setattr(delivery_member_close_steps, "prepare_member_close", no_close)
    monkeypatch.setattr(delivery_member_close_steps, "stage_member_close", no_close)
    assert unresolved_blocking_qa(test_db, RUN) == []
    before = test_db.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0]
    [row] = run_progress(test_db, project_id=1, now=parse_instant(NOW))
    assert row.outstanding == row.total_blocking == 0
    assert row.completion.blocked and row.needs_action
    rendered = "\n".join(_run_lines((row,)))
    assert render_item_ref(test_db, SECOND) in rendered
    assert f"requirement #{requirement_id}" in rendered
    assert "phase=manual_acceptance" in rendered and "target=stage" in rendered
    assert f"{render_item_ref(test_db, FIRST)} (held atomically)" in rendered
    assert "Nothing is outstanding" not in rendered
    assert "re-drive" not in row.recovery()
    assert "run_settlement_blocked" in row.recovery()
    assert _run_dict(row)["member_closure_blocked"]
    diagnostic = run_completion_diagnostics(RUN)
    assert diagnostic["blocked"] and len(diagnostic["members"]) == 2
    assert test_db.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0] == before
    assert _status(test_db, FIRST) == _status(test_db, SECOND) == status

    # Fixture proof answers the existing requirement; no production mutation.
    test_db.execute(
        "INSERT INTO qa_runs(qa_requirement_id,qa_kind,performed_by,verdict,created_at,started_at,completed_at) "
        "VALUES (%s,'command','human','pass',%s,%s,%s)",
        (requirement_id, NOW, NOW, NOW),
    )
    test_db.execute(
        "INSERT INTO qa_runs(qa_requirement_id,qa_kind,performed_by,verdict,created_at,started_at,completed_at) "
        "SELECT id,qa_kind,'agent','pass',%s,%s,%s FROM qa_requirements "
        "WHERE item_id=%s AND qa_phase='verification'",
        (NOW, NOW, NOW, SECOND),
    )
    test_db.commit()
    fresh = completion_preview(test_db, RUN)
    assert not fresh.blocked
    assert "manual_acceptance" not in "\n".join(fresh.lines)
    assert "held atomically" not in "\n".join(fresh.lines)
    assert "Nothing is outstanding" not in fresh.recovery(RUN)


def test_no_answer_is_a_member_blocker_and_no_members_is_pending_effects(test_db):
    _seed(test_db, answer_first=False)
    test_db.commit()
    preview = completion_preview(test_db, RUN)
    assert "post-deploy obligations" in "\n".join(preview.lines)
    test_db.execute(
        "UPDATE items SET status='done' WHERE id IN (%s,%s)", (FIRST, SECOND)
    )
    test_db.commit()
    preview = completion_preview(test_db, RUN)
    assert not preview.members and not preview.blocked
    assert "finalization effects remain pending" in preview.recovery(RUN)


def test_driver_recovery_does_not_invite_a_second_dispatch(test_db):
    _seed(test_db)
    [row] = run_progress(test_db, project_id=1, now=parse_instant(NOW))
    live = replace(
        row,
        completion=type(row.completion)(),
        status="created",
        driver_phase="freezing_source",
    )
    assert "Live driver freezing_source owns this run" in live.recovery()
    assert "re-drive" not in live.recovery()
    stopped = replace(live, driver_phase="")
    assert f"re-drive {RUN} to start" in stopped.recovery()
    test_db.execute("UPDATE deployment_runs SET settling_at=NULL WHERE id=%s", (RUN,))
    test_db.commit()
    assert completion_preview(test_db, RUN).members == ()


def test_other_target_deferral_does_not_invent_an_atomic_run_blocker(test_db):
    requirement_id = _seed(test_db, required=False)
    preview = completion_preview(test_db, RUN)
    assert not preview.blocked
    assert "deferred to other target" in "\n".join(preview.lines)
    assert f"requirement #{requirement_id}" in "\n".join(preview.lines)
    assert "held atomically" not in "\n".join(preview.lines)


def test_missing_landing_evidence_is_named_before_calling_a_sibling_ready(test_db):
    from runtime.api.domain.test_deployment_delivery_close_out_notice import (
        _member_at_release_wait,
    )

    _project(test_db)
    _member_at_release_wait(test_db, FIRST)
    _no_obligation(test_db, FIRST, reason="nothing observable once deployed")
    _executing_run(test_db, RUN, (FIRST,))
    test_db.execute("UPDATE deployment_runs SET settling_at=%s WHERE id=%s", (NOW, RUN))
    test_db.commit()
    preview = completion_preview(test_db, RUN)
    assert preview.blocked
    assert "landing evidence is missing execution_evidence" in "\n".join(preview.lines)


def test_unreadable_member_contract_never_becomes_an_all_clear(test_db, monkeypatch):
    from yoke_core.domain import deployment_run_collective_finalization as owner

    _seed(test_db)

    def unavailable(*args):
        raise ValueError("frozen member identity is unavailable")

    monkeypatch.setattr(owner, "_split_waiting_members", unavailable)
    preview = completion_preview(test_db, RUN)
    assert preview.blocked
    assert "frozen member identity is unavailable" in "\n".join(preview.lines)
    assert "member_closure_unavailable" in preview.recovery(RUN)
    assert "Nothing is outstanding" not in preview.recovery(RUN)
