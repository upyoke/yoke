"""Settlement closes a shared gate's members in one commit, then runs effects.

The commit phase writes every member's close on the settlement's own
connection and commits once, so a refusal anywhere rolls the whole set back.
The effects phase runs after that commit and is idempotent: a failure there
never reopens a closed member, and the next replay finishes it.
"""

from __future__ import annotations

from runtime.api.domain.shared_gate_two_phase_settlement_test_support import (
    MEMBERS as MEMBERS,
    REASON as REASON,
    _executing_run as _executing_run,
    _five_ready_members as _five_ready_members,
    _holder as _holder,
)


from typing import Any

from runtime.api.domain.run_success_member_settlement_test_support import (
    _claim_held,
    _run,
    _status,
)
from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)
from runtime.api.fixtures.dispatch_actor import register_session_actor
from runtime.api.fixtures.runtime import DEFAULT_TEST_SESSION_ID
from yoke_core.domain import delivery_member_close_effects as close_effects
from yoke_core.domain import delivery_member_close_steps as close_out
from yoke_core.domain.deployment_run_collective_finalization import mark_settling
from yoke_core.domain.deployment_run_settlement_refusal import HELD_WITH_RUN
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.project_identity import render_item_ref


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
    real_effects = close_effects.run_closed_member_effects

    def _stage(conn, **kwargs):
        timeline.append(("write", id(conn)))
        return real_stage(conn, **kwargs)

    def _effects(**kwargs):
        timeline.append(("effects", 0))
        return real_effects(**kwargs)

    connection_type = type(test_db)
    real_commit = connection_type.commit

    def _commit(self):
        timeline.append(("commit", id(self)))
        return real_commit(self)

    monkeypatch.setattr(close_out, "stage_member_close", _stage)
    monkeypatch.setattr(close_effects, "run_closed_member_effects", _effects)
    monkeypatch.setattr(connection_type, "commit", _commit)

    assert cmd_update("run-one-commit", "status", "succeeded") is None

    settling = next(conn for step, conn in timeline if step == "write")
    first_effect = next(i for i, (step, _) in enumerate(timeline) if step == "effects")
    steps = [step for step, conn in timeline[:first_effect] if conn == settling]
    closing = steps[steps.index("write") :]
    assert closing[: len(MEMBERS) + 1] == ["write"] * len(MEMBERS) + ["commit"]
    assert set(closing[len(MEMBERS) + 1 :]) <= {"commit"}
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
    from yoke_core.domain import standalone_item_merge

    synced: list[int] = []

    def _broken(item_id: int):
        raise RuntimeError("GitHub sync unavailable")

    monkeypatch.setattr(standalone_item_merge, "sync_item_to_github", _broken)

    refusal = cmd_update("run-effects", "status", "succeeded")

    assert refusal is not None and "GitHub sync unavailable" in refusal
    assert "post-close effects did not finish" in refusal
    assert _run(test_db, "run-effects") == ("executing", True)
    for item_id in MEMBERS:
        assert _status(test_db, item_id) == "done"
        assert not _claim_held(test_db, item_id)

    def _sync(item_id: int):
        synced.append(int(item_id))
        return None

    monkeypatch.setattr(standalone_item_merge, "sync_item_to_github", _sync)
    assert cmd_update("run-effects", "status", "succeeded") is None

    assert sorted(synced) == sorted(MEMBERS)
    assert _run(test_db, "run-effects") == ("succeeded", True)


def test_a_run_whose_members_are_partly_closed_still_converges(
    test_db: Any, monkeypatch
) -> None:
    """Members closed before settlement began — by their own close-out, or
    by an earlier pass — are neither closed twice nor a blocker."""
    _isolate_status_effects(monkeypatch)
    register_session_actor(test_db, DEFAULT_TEST_SESSION_ID)
    _five_ready_members(test_db)
    _executing_run(test_db, "run-partial")
    mark_settling(test_db, "run-partial")
    for item_id in MEMBERS[:2]:
        public_ref = render_item_ref(test_db, item_id)
        assert not close_out.prepare_member_close(
            test_db, item_id=item_id, public_ref=public_ref, run_id="run-recovery"
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
