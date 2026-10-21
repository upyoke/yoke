"""A close-out the done write would refuse for unsettled QA stops before it.

Every dispatch re-tries each accepted member's close-out. A member held by
an unsettled QA record used to run the status preflight and the whole done
write, whose later gates reach git and GitHub, on every call. Its refusal is
now read from the same settlement rows first, and the close runs once they
settle.
"""

from __future__ import annotations

from runtime.api.domain.test_deployment_delivery_close_out_notice import _project
from runtime.api.domain.test_member_close_out_round_trips import _seed
from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from yoke_core.domain import backlog
from yoke_core.domain import deployment_run_carried_work_source as sources
from yoke_core.domain import workflow_status_transition_preflight as preflight
from yoke_core.domain.no_obligation_member_close_out import (
    close_out_satisfied_delivery_member,
)

RUN_ID = "run-close-out-small"


def _unsettled_requirement(conn, member: int) -> int:
    """An item verification requirement whose latest execution has no verdict."""
    columns = [
        str(row[0])
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='qa_requirements' AND column_name<>'id'"
        ).fetchall()
    ]
    overrides = {
        "waived_at": "NULL",
        "waiver_rationale": "NULL",
        "waiver_source": "NULL",
        "deployment_run_id": "NULL",
        "deployment_stage": "NULL",
        "deployment_member_item_id": "NULL",
        "item_id": str(int(member)),
        "qa_phase": "'verification'",
    }
    selected = ",".join(overrides.get(column, column) for column in columns)
    requirement = conn.execute(
        f"INSERT INTO qa_requirements({','.join(columns)}) SELECT {selected} "
        "FROM qa_requirements WHERE deployment_run_id=%s ORDER BY id LIMIT 1 "
        "RETURNING id",
        (RUN_ID,),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,started_at,"
        "created_at) VALUES (%s,'worktree_run','plan_case',NOW(),NOW())",
        (requirement,),
    )
    conn.commit()
    return int(requirement)


def _close(conn, member):
    return close_out_satisfied_delivery_member(
        conn, item_id=member, public_ref="", run_id=RUN_ID
    )


def test_unsettled_member_refuses_before_the_done_write(test_db, monkeypatch):
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    member = _seed(test_db, RUN_ID)
    requirement = _unsettled_requirement(test_db, member)
    attempts = []
    real_preflight = preflight.prepare_status_transition
    real_update = backlog.execute_update

    def refuse(*_args, **_kwargs):
        raise AssertionError("a refused close-out reached git or GitHub")

    monkeypatch.setattr(sources, "carried_work_sources", refuse)
    monkeypatch.setattr(
        preflight,
        "prepare_status_transition",
        lambda *a, **k: attempts.append("preflight") or real_preflight(*a, **k),
    )
    monkeypatch.setattr(
        backlog,
        "execute_update",
        lambda *a, **k: attempts.append("done write") or real_update(*a, **k),
    )

    for _call in range(2):
        refused = _close(test_db, member)
        assert refused.applies and not refused.ok
        assert "QA record(s) are unsettled" in refused.detail
        assert f"requirement {requirement} latest execution" in refused.detail
    assert attempts == []

    test_db.execute(
        "UPDATE qa_requirements SET waived_at=NOW(),waiver_rationale='accepted',"
        "waiver_source='owner' WHERE id=%s",
        (requirement,),
    )
    test_db.commit()
    assert _close(test_db, member).detail == "closed"
    assert attempts[:2] == ["preflight", "done write"]
