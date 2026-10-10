"""A shared gate closes every member of its run, or none of them.

The gate passes for the run. Closing one member and leaving the other at its
release wait applies that one verdict to only part of what it covered, and the
member that closed has already released the claim and lane its recovery would
need.

Residue is settled on the way through: an item-level QA execution that
recorded no result cannot be the reason a member stays open, because the walk
that would abort it is the run's own scoped item QA, which already finished.
An execution that did record something keeps refusing, and holds the whole run
with it.
"""

from __future__ import annotations

from typing import Any

from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from runtime.api.domain.test_deployment_delivery_close_out_notice import (
    COMPLETION_FLOW,
    _project,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    HOLDER_B,
)
from runtime.api.domain.test_no_obligation_member_close_out import (
    _no_obligation,
    _ready_member,
)
from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_run_collective_finalization import HELD_WITH_RUN
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_plan_execution_store import roster_digest
from yoke_core.domain.qa_resultless_execution_supersession import SUPERSESSION_REASON

FIRST_ITEM = 9871
SECOND_ITEM = 9872
REASON = "nothing observable once deployed"


def _executing_run(conn: Any, run_id: str, members: tuple[int, ...]) -> None:
    """A run whose stages are done and whose shared gate has passed.

    ``current_stage='complete'`` is the state settlement actually runs in: the
    driver finished the pinned stages and detached before the shared gate
    resolved.
    """
    now = iso8601_now()
    conn.execute(
        "INSERT INTO deployment_runs "
        "(id,project_id,flow,status,current_stage,created_at) "
        "VALUES (%s,1,%s,'executing','complete',%s)",
        (run_id, COMPLETION_FLOW, now),
    )
    from runtime.api.fixtures.completed_delivery import pin_run_delivery

    pin_run_delivery(conn, run_id)
    for item_id in members:
        conn.execute(
            "INSERT INTO deployment_run_items (run_id,item_id,added_at) "
            "VALUES (%s,%s,%s)",
            (run_id, item_id, now),
        )
    conn.commit()


def _item_level_execution(
    conn: Any, execution_id: str, item_id: int, *, cursor_ordinal: int = 0
) -> str:
    """An item-level execution the member's own release walk opened."""
    conn.execute(
        "INSERT INTO qa_plan_executions "
        "(id,item_id,transition_id,session_id,roster_digest,roster_json,"
        "cursor_ordinal,state,created_at,heartbeat_at) "
        "VALUES (%s,%s,'release',%s,%s,'[]',%s,'active',%s,%s)",
        (
            execution_id,
            item_id,
            f"session-{item_id}",
            roster_digest([]),
            cursor_ordinal,
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:00Z",
        ),
    )
    conn.commit()
    return execution_id


def _execution_state(conn: Any, execution_id: str) -> tuple[str, str]:
    row = conn.execute(
        "SELECT state,release_reason FROM qa_plan_executions WHERE id=%s",
        (execution_id,),
    ).fetchone()
    return str(row["state"]), str(row["release_reason"] or "")


def _run_status(conn: Any, run_id: str) -> tuple[str, bool]:
    row = conn.execute(
        "SELECT status,settling_at FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    return str(row["status"]), bool(row["settling_at"])


def _status(conn: Any, item_id: int) -> str:
    return conn.execute("SELECT status FROM items WHERE id=%s", (item_id,)).fetchone()[
        "status"
    ]


def _two_ready_members(conn: Any) -> str:
    _project(conn)
    for item_id, holder in ((FIRST_ITEM, HOLDER_A), (SECOND_ITEM, HOLDER_B)):
        _ready_member(conn, item_id, holder)
        _no_obligation(conn, item_id, reason=REASON)
    return _status(conn, FIRST_ITEM)


def test_a_resultless_item_execution_is_superseded_so_every_member_closes(
    test_db: Any, monkeypatch
) -> None:
    """The observed stranding: one member's release walk left a live
    execution that never recorded anything, and the run's own scoped item QA
    passed instead. It carries no evidence, so it is superseded here."""
    _isolate_status_effects(monkeypatch)
    _two_ready_members(test_db)
    execution_id = _item_level_execution(test_db, "execution-residue", SECOND_ITEM)
    _executing_run(test_db, "run-residue", (FIRST_ITEM, SECOND_ITEM))

    assert cmd_update("run-residue", "status", "succeeded") is None

    assert _run_status(test_db, "run-residue") == ("succeeded", True)
    for item_id in (FIRST_ITEM, SECOND_ITEM):
        assert _status(test_db, item_id) == "done"
    assert _execution_state(test_db, execution_id) == (
        "aborted",
        SUPERSESSION_REASON,
    )


def test_an_execution_that_recorded_a_result_holds_every_member(
    test_db: Any, monkeypatch
) -> None:
    """Real unsettled evidence keeps refusing, and the sibling that could
    close is held with the run rather than closed on its own."""
    _isolate_status_effects(monkeypatch)
    release = _two_ready_members(test_db)
    execution_id = _item_level_execution(
        test_db, "execution-evidence", SECOND_ITEM, cursor_ordinal=1
    )
    _executing_run(test_db, "run-blocked", (FIRST_ITEM, SECOND_ITEM))

    refusal = cmd_update("run-blocked", "status", "succeeded")

    assert refusal is not None and "is settling" in refusal
    assert f"plan execution #{execution_id}" in refusal
    assert render_item_ref(test_db, SECOND_ITEM) in refusal
    # The sibling is named as held, not as broken: nothing about it to repair.
    assert HELD_WITH_RUN in refusal
    assert render_item_ref(test_db, FIRST_ITEM) in refusal
    assert _run_status(test_db, "run-blocked") == ("executing", True)
    for item_id in (FIRST_ITEM, SECOND_ITEM):
        assert _status(test_db, item_id) == release
    assert _execution_state(test_db, execution_id)[0] == "active"


def test_clearing_the_blocker_replays_settlement_without_a_hand_re_drive(
    test_db: Any, monkeypatch
) -> None:
    """Aborting the record that held the run finishes the run on that same
    event. A shared gate that already passed must not wait on somebody
    noticing and re-driving `deployment-runs update status succeeded`."""
    from runtime.api.domain.test_independent_member_delivery_close_out import (
        MEMBER_A,
        MEMBER_B,
        _seed_final_run,
        _settle,
    )
    from yoke_core.domain.deployment_run_auto_completion import finish_ready_run
    from yoke_core.domain.deployment_run_driver_attachment import (
        PHASE_EXECUTING,
        attach_driver,
        release_driver,
    )
    from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
    from yoke_core.domain.qa_plan_execution_store import lock_plan_execution

    _isolate_status_effects(monkeypatch)
    run_id = "run-replayed"
    _seed_final_run(test_db, run_id, shared_qa=True)
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_A)
    _settle(test_db, run_id=run_id, stage="item-qa", member=MEMBER_B)
    test_db.execute(
        "UPDATE deployment_runs SET current_stage='run-qa' WHERE id=%s", (run_id,)
    )
    test_db.commit()
    # The live driver owns the continuation while the last gate is accepted;
    # it then detaches with only the members' own close-outs left. Residue
    # with a recorded result is a real blocker, not something settlement may
    # supersede on its own.
    release_seeded_driver(test_db, run_id)
    attach_driver(
        test_db, run_id, session_id="deploy-driver", pid=4242, phase=PHASE_EXECUTING
    )
    test_db.commit()
    _settle(test_db, run_id=run_id, stage="run-qa", member=None, may_complete_run=True)
    execution_id = _item_level_execution(
        test_db, "execution-cleared", MEMBER_B, cursor_ordinal=1
    )
    assert release_driver(test_db, run_id, session_id="deploy-driver", pid=4242)
    test_db.commit()

    assert not finish_ready_run(test_db, run_id).completed
    assert _run_status(test_db, run_id) == ("executing", True)
    assert _status(test_db, MEMBER_A) == _status(test_db, MEMBER_B) == "release"

    finish_plan_execution(
        test_db,
        lock_plan_execution(test_db, execution_id),
        state="aborted",
        reason="walker abandoned the release walk",
    )

    assert _run_status(test_db, run_id) == ("succeeded", True)
    assert _status(test_db, MEMBER_A) == _status(test_db, MEMBER_B) == "done"


def test_a_member_owing_its_post_deploy_answer_keeps_its_live_execution(
    test_db: Any, monkeypatch
) -> None:
    """Supersession is offered only where this run's own item QA is already
    satisfied. Until then a live execution is the member's real work, so it
    survives settlement untouched."""
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, FIRST_ITEM, HOLDER_A)
    _no_obligation(test_db, FIRST_ITEM, reason=REASON)
    # No post-deploy answer of any kind: this member owes the run.
    _ready_member(test_db, SECOND_ITEM, HOLDER_B)
    release = _status(test_db, SECOND_ITEM)
    execution_id = _item_level_execution(test_db, "execution-owed", SECOND_ITEM)
    _executing_run(test_db, "run-owed", (FIRST_ITEM, SECOND_ITEM))

    refusal = cmd_update("run-owed", "status", "succeeded")

    assert refusal is not None and "is settling" in refusal
    assert render_item_ref(test_db, SECOND_ITEM) in refusal
    assert _run_status(test_db, "run-owed") == ("executing", True)
    for item_id in (FIRST_ITEM, SECOND_ITEM):
        assert _status(test_db, item_id) == release
    assert _execution_state(test_db, execution_id) == ("active", "")
