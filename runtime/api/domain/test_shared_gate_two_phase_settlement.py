"""Settlement closes a shared gate's members in one commit, then runs effects.

The commit phase writes every member's close on the settlement's own
connection and commits once, so a refusal anywhere rolls the whole set back.
The effects phase runs after that commit and is idempotent: a failure there
never reopens a closed member, and the next replay finishes it.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_deployment_delivery_close_out_notice import (
    COMPLETION_FLOW,
    _member_at_release_wait,
    _parked_owner,
    _project,
)
from runtime.api.domain.test_no_obligation_member_close_out import (
    _no_obligation,
    _ready_member,
)
from runtime.api.domain.test_run_success_member_settlement import (
    _claim_held,
    _run,
    _status,
)
from runtime.api.domain.test_status_transition_preflight import (
    _isolate_status_effects,
)
from yoke_core.domain import delivery_member_close_steps as close_out
from yoke_core.domain import terminal_lane_cleanup
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_run_collective_finalization import (
    HELD_WITH_RUN,
    mark_settling,
)
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.project_identity import render_item_ref

MEMBERS = (9861, 9862, 9863, 9864, 9865)
REASON = "nothing observable once deployed"


def _holder(item_id: int) -> str:
    return f"sess-settle-holder-{item_id}"


def _executing_run(conn: Any, run_id: str) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO deployment_runs (id,project_id,flow,status,created_at) "
        "VALUES (%s,1,%s,'executing',%s)",
        (run_id, COMPLETION_FLOW, now),
    )
    from runtime.api.fixtures.completed_delivery import pin_run_delivery

    pin_run_delivery(conn, run_id)
    for item_id in MEMBERS:
        conn.execute(
            "INSERT INTO deployment_run_items (run_id,item_id,added_at) "
            "VALUES (%s,%s,%s)",
            (run_id, item_id, now),
        )
    conn.commit()


def _five_ready_members(conn: Any, *, without_evidence: int = 0) -> str:
    _project(conn)
    for item_id in MEMBERS:
        if item_id == without_evidence:
            _member_at_release_wait(conn, item_id)
            _parked_owner(conn, _holder(item_id), item_id)
        else:
            _ready_member(conn, item_id, _holder(item_id))
        _no_obligation(conn, item_id, reason=REASON)
    return _status(conn, MEMBERS[0])


def test_five_members_close_in_one_commit(test_db: Any, monkeypatch) -> None:
    """Every member's close is written on the settlement's connection
    before the one commit that lands them all, and no effect runs until
    that commit has happened. Other connections — an event written on its
    own, say — commit nothing the members depend on."""
    _isolate_status_effects(monkeypatch)
    _five_ready_members(test_db)
    _executing_run(test_db, "run-one-commit")
    timeline: list[tuple[str, int]] = []
    real_stage = close_out.stage_member_close
    real_effects = close_out.run_closed_member_effects

    def _stage(conn, **kwargs):
        timeline.append(("write", id(conn)))
        return real_stage(conn, **kwargs)

    def _effects(conn, **kwargs):
        timeline.append(("effects", id(conn)))
        return real_effects(conn, **kwargs)

    connection_type = type(test_db)
    real_commit = connection_type.commit

    def _commit(self):
        timeline.append(("commit", id(self)))
        return real_commit(self)

    monkeypatch.setattr(close_out, "stage_member_close", _stage)
    monkeypatch.setattr(close_out, "run_closed_member_effects", _effects)
    monkeypatch.setattr(connection_type, "commit", _commit)

    assert cmd_update("run-one-commit", "status", "succeeded") is None

    settling = next(conn for step, conn in timeline if step == "write")
    steps = [step for step, conn in timeline if conn == settling]
    closing = steps[steps.index("write") : steps.index("effects")]
    assert closing == ["write"] * len(MEMBERS) + ["commit"]
    assert _run(test_db, "run-one-commit") == ("succeeded", True)
    for item_id in MEMBERS:
        assert _status(test_db, item_id) == "done"
        assert not _claim_held(test_db, item_id)


def test_a_refusal_on_the_third_member_leaves_all_five_open(
    test_db: Any, monkeypatch
) -> None:
    """The third member's close refuses after two siblings were already
    written; the whole set rolls back and the run stays settling."""
    _isolate_status_effects(monkeypatch)
    blocked = MEMBERS[2]
    release = _five_ready_members(test_db, without_evidence=blocked)
    _executing_run(test_db, "run-refused")

    refusal = cmd_update("run-refused", "status", "succeeded")

    assert refusal is not None and "is settling" in refusal
    assert f"{render_item_ref(test_db, blocked)}: landing evidence is missing" in (
        refusal
    )
    for item_id in MEMBERS:
        if item_id != blocked:
            assert f"{render_item_ref(test_db, item_id)}: {HELD_WITH_RUN}" in refusal
    assert _run(test_db, "run-refused") == ("executing", True)
    for item_id in MEMBERS:
        assert _status(test_db, item_id) == release
        assert _claim_held(test_db, item_id)


def test_an_effects_failure_keeps_members_done_and_replay_finishes_it(
    test_db: Any, monkeypatch
) -> None:
    """A failed effect never reopens a closed member. The run stays settling
    until a replay finishes every member's effects, then reads succeeded."""
    _isolate_status_effects(monkeypatch)
    _five_ready_members(test_db)
    _executing_run(test_db, "run-effects")
    retired: list[int] = []

    def _broken(item, envelope, **_kwargs):
        raise RuntimeError("lane cleanup unavailable")

    monkeypatch.setattr(
        terminal_lane_cleanup, "record_terminal_lane_close_out", _broken
    )

    refusal = cmd_update("run-effects", "status", "succeeded")

    assert refusal is not None and "lane cleanup unavailable" in refusal
    assert "post-close effects did not finish" in refusal
    assert _run(test_db, "run-effects") == ("executing", True)
    for item_id in MEMBERS:
        assert _status(test_db, item_id) == "done"
        assert not _claim_held(test_db, item_id)

    def _retire(item, envelope, **_kwargs):
        retired.append(int(item["id"]))

    monkeypatch.setattr(
        terminal_lane_cleanup, "record_terminal_lane_close_out", _retire
    )
    assert cmd_update("run-effects", "status", "succeeded") is None

    assert sorted(retired) == list(MEMBERS)
    assert _run(test_db, "run-effects") == ("succeeded", True)


def test_a_run_whose_members_are_partly_closed_still_converges(
    test_db: Any, monkeypatch
) -> None:
    """Members closed before settlement began — by their own close-out, or
    by an earlier pass — are neither closed twice nor a blocker."""
    _isolate_status_effects(monkeypatch)
    _five_ready_members(test_db)
    _executing_run(test_db, "run-partial")
    mark_settling(test_db, "run-partial")
    for item_id in MEMBERS[:2]:
        public_ref = render_item_ref(test_db, item_id)
        assert not close_out.prepare_member_close(
            test_db, item_id=item_id, public_ref=public_ref
        )
        staged = close_out.stage_member_close(
            test_db, item_id=item_id, public_ref=public_ref
        )
        assert not staged.refusal
        test_db.commit()

    assert cmd_update("run-partial", "status", "succeeded") is None

    assert _run(test_db, "run-partial") == ("succeeded", True)
    for item_id in MEMBERS:
        assert _status(test_db, item_id) == "done"
        assert not _claim_held(test_db, item_id)
