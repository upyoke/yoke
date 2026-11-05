"""A run reads succeeded only after every cleared member has closed.

Settlement is durable and non-terminal: a real close-out refusal or an
interrupted process leaves the run executing and settling, and every member
at its release wait with its claim. The next re-drive replays settlement
from there.
"""

from __future__ import annotations

from runtime.api.domain.run_success_member_settlement_test_support import (
    FIRST_ITEM as FIRST_ITEM,
    REASON as REASON,
    SECOND_ITEM as SECOND_ITEM,
    _claim_held as _claim_held,
    _executing_run as _executing_run,
    _run as _run,
    _status as _status,
)


from runtime.api.fixtures.backlog_inserts import insert_deployment_run

from typing import Any

import pytest

from runtime.api.domain.deployment_delivery_close_out_notice_test_support import (
    COMPLETION_FLOW,
    _member_at_release_wait,
    _parked_owner,
    _project,
)
from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    HOLDER_B,
)
from runtime.api.domain.no_obligation_member_close_out_test_support import (
    _landing_evidence,
    _no_obligation,
    _ready_member,
)
from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)
from yoke_core.domain import delivery_member_close_steps as close_out
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.project_identity import render_item_ref


def _two_ready_members(conn: Any) -> str:
    _project(conn)
    for item_id, holder in ((FIRST_ITEM, HOLDER_A), (SECOND_ITEM, HOLDER_B)):
        _ready_member(conn, item_id, holder)
        _no_obligation(conn, item_id, reason=REASON)
    return _status(conn, FIRST_ITEM)


def test_a_refused_close_out_holds_every_member_until_re_driven(
    test_db: Any, monkeypatch
) -> None:
    """One member that cannot close holds the whole run. The sibling that
    could close keeps its claim and lane instead of being closed alone, so a
    shared gate never lands on part of what it covered."""
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, FIRST_ITEM, HOLDER_A)
    _no_obligation(test_db, FIRST_ITEM, reason=REASON)
    # Answered, but landed no evidence: its real close-out refuses.
    _member_at_release_wait(test_db, SECOND_ITEM)
    _parked_owner(test_db, HOLDER_B, SECOND_ITEM)
    _no_obligation(test_db, SECOND_ITEM, reason=REASON)
    release = _status(test_db, SECOND_ITEM)
    _executing_run(test_db, "run-settling", (FIRST_ITEM, SECOND_ITEM))

    refusal = cmd_update("run-settling", "status", "succeeded")

    assert refusal is not None and "is settling" in refusal
    assert render_item_ref(test_db, SECOND_ITEM) in refusal
    assert "landing evidence is missing" in refusal
    assert "yoke deployment-runs update run-settling status succeeded" in refusal
    assert _run(test_db, "run-settling") == ("executing", True)
    for item_id in (FIRST_ITEM, SECOND_ITEM):
        assert _status(test_db, item_id) == release
        assert _claim_held(test_db, item_id)

    _landing_evidence(test_db, SECOND_ITEM)
    assert cmd_update("run-settling", "status", "succeeded") is None

    assert _run(test_db, "run-settling") == ("succeeded", True)
    for item_id in (FIRST_ITEM, SECOND_ITEM):
        assert _status(test_db, item_id) == "done"
        assert not _claim_held(test_db, item_id)


def test_an_interrupted_settlement_closes_nothing_and_replays(
    test_db: Any, monkeypatch
) -> None:
    """A process that dies after writing one member's close commits none of
    them: every member is written in one transaction, so the next re-drive
    starts from members that are all still at their wait."""
    _isolate_status_effects(monkeypatch)
    release = _two_ready_members(test_db)
    _executing_run(test_db, "run-interrupted", (FIRST_ITEM, SECOND_ITEM))
    real = close_out.stage_member_close
    written: list[int] = []

    def _crash_after_first(conn, **kwargs):
        if written:
            raise SystemExit("settling process died")
        staged = real(conn, **kwargs)
        written.append(int(kwargs["item_id"]))
        return staged

    monkeypatch.setattr(close_out, "stage_member_close", _crash_after_first)
    with pytest.raises(SystemExit, match="settling process died"):
        cmd_update("run-interrupted", "status", "succeeded")

    assert _run(test_db, "run-interrupted") == ("executing", True)
    for item_id in (FIRST_ITEM, SECOND_ITEM):
        assert _status(test_db, item_id) == release
        assert _claim_held(test_db, item_id)

    monkeypatch.setattr(close_out, "stage_member_close", real)
    assert cmd_update("run-interrupted", "status", "succeeded") is None

    assert _run(test_db, "run-interrupted") == ("succeeded", True)
    for item_id in (FIRST_ITEM, SECOND_ITEM):
        assert _status(test_db, item_id) == "done"


def test_run_success_closes_every_ready_member_with_it(
    test_db: Any, monkeypatch, capsys
) -> None:
    _isolate_status_effects(monkeypatch)
    _two_ready_members(test_db)
    _executing_run(test_db, "run-settled", (FIRST_ITEM, SECOND_ITEM))

    assert cmd_update("run-settled", "status", "succeeded") is None

    assert _run(test_db, "run-settled") == ("succeeded", True)
    for item_id in (FIRST_ITEM, SECOND_ITEM):
        assert _status(test_db, item_id) == "done"
        assert not _claim_held(test_db, item_id)
    output = capsys.readouterr().out
    for item_id in (FIRST_ITEM, SECOND_ITEM):
        ref = render_item_ref(test_db, item_id)
        assert f"Run run-settled: preparing {ref} close-out" in output
        assert f"Run run-settled: finishing {ref} close-out effects" in output


def test_an_uncleared_member_holds_the_run_until_answered(
    test_db: Any, monkeypatch
) -> None:
    """A final member with no post-deploy answer is never cleared, so no
    close-out even runs for it; success still waits for it by name."""
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, FIRST_ITEM, HOLDER_A)
    release = _status(test_db, FIRST_ITEM)
    _executing_run(test_db, "run-unanswered", (FIRST_ITEM,))

    refusal = cmd_update("run-unanswered", "status", "succeeded")

    assert refusal is not None
    assert render_item_ref(test_db, FIRST_ITEM) in refusal
    assert "post-deploy obligations on this run are not all answered" in refusal
    assert _run(test_db, "run-unanswered") == ("executing", True)
    assert _status(test_db, FIRST_ITEM) == release
    assert _claim_held(test_db, FIRST_ITEM)

    _no_obligation(test_db, FIRST_ITEM, reason=REASON)
    assert cmd_update("run-unanswered", "status", "succeeded") is None
    assert _run(test_db, "run-unanswered") == ("succeeded", True)
    assert _status(test_db, FIRST_ITEM) == "done"


def test_a_cancelled_duplicate_does_not_block_re_driving_the_settling_run(
    test_db: Any, monkeypatch
) -> None:
    """A duplicate enrolled the member and was cancelled before it executed;
    the settling run that actually delivered still closes the member."""
    _isolate_status_effects(monkeypatch)
    _project(test_db)
    _ready_member(test_db, FIRST_ITEM, HOLDER_A)
    _no_obligation(test_db, FIRST_ITEM, reason=REASON)
    _executing_run(test_db, "run-delivering", (FIRST_ITEM,))
    test_db.execute(
        "UPDATE deployment_runs SET settling_at=%s, created_at=%s WHERE id=%s",
        ("2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z", "run-delivering"),
    )
    insert_deployment_run(
        test_db,
        id="run-duplicate",
        project_id=1,
        flow=COMPLETION_FLOW,
        status="cancelled",
        created_at="2026-01-01T00:00:27Z",
    )
    test_db.execute(
        "INSERT INTO deployment_run_items (run_id,item_id,added_at) "
        "VALUES ('run-duplicate',%s,'2026-01-01T00:00:27Z')",
        (FIRST_ITEM,),
    )
    test_db.commit()

    assert cmd_update("run-delivering", "status", "succeeded") is None

    assert _run(test_db, "run-delivering") == ("succeeded", True)
    assert _status(test_db, FIRST_ITEM) == "done"
