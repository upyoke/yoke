"""Queued QA walks are abandoned only on durable owner-session end."""

from __future__ import annotations

import pytest

from runtime.api.domain.machine_qa_session_seed import seed_qa_session
from runtime.api.domain.test_qa_plan_execution_authority import _materialize_two_cases
from yoke_contracts.timestamps import utc_now
from yoke_core.domain.qa_plan_execution_authority import (
    plan_execution_abort_authority,
    plan_execution_is_abandoned,
)
from yoke_core.domain.qa_plan_execution_lifecycle import reap_stale_plan_executions
from yoke_core.domain.qa_plan_execution_state import (
    QaPlanExecutionStateError,
    begin_plan_execution,
    select_plan_execution,
)
from yoke_core.domain.qa_stage_execution_holders import abort_abandoned_holders

OWNER = "queued-walk-owner"
OLD = "2026-01-01T00:00:00Z"


def _begin(conn, session=OWNER):
    return begin_plan_execution(
        conn, item_id=4909, transition_id="implemented",
        actor_id="1", session_id=session,
    )


@pytest.mark.parametrize("path", ["reap", "begin", "stage-holder", "abort-authority"])
@pytest.mark.parametrize(
    "state,ended,stale,abandoned",
    [
        ("waiting", False, True, False),
        ("waiting", True, True, True),
        ("waiting", True, False, True),
        ("active", False, True, True),
    ],
)
def test_abandonment_paths_follow_waiting_owner_lifetime(
    test_db, monkeypatch, path, state, ended, stale, abandoned,
):
    seed_qa_session(test_db, OWNER)
    _materialize_two_cases(test_db, item_id=4909)
    execution = _begin(test_db)
    test_db.execute(
        "UPDATE qa_plan_executions SET state=%s,heartbeat_at=%s WHERE id=%s",
        (state, OLD if stale else utc_now(), execution["id"]),
    )
    test_db.execute(
        "UPDATE harness_sessions SET mode='dash',ended_at=%s WHERE session_id=%s",
        (OLD if ended else None, OWNER),
    )
    test_db.commit()

    if path == "reap":
        reaped = reap_stale_plan_executions(test_db)
        assert [row["execution_id"] for row in reaped] == (
            [execution["id"]] if abandoned else []
        )
    elif path == "begin":
        if abandoned:
            assert _begin(test_db, "competing-owner")["id"] != execution["id"]
        else:
            with pytest.raises(QaPlanExecutionStateError, match="another actor or session"):
                _begin(test_db, "competing-owner")
    elif path == "stage-holder":
        # Isolate discovery; exercise the real lock, authority and settlement.
        monkeypatch.setattr(
            "yoke_core.domain.qa_stage_execution_holders.live_stage_executions",
            lambda *_args, **_kwargs: [select_plan_execution(
                test_db, execution["id"], lock=False,
            )],
        )
        assert abort_abandoned_holders(
            test_db, execution["roster"], deployment_run_id="test-run",
            deployment_stage="item-qa", session_id="competing-owner",
        ) is abandoned
    else:
        stored = select_plan_execution(test_db, execution["id"], lock=False)
        if abandoned:
            assert plan_execution_abort_authority(
                test_db, stored, item_id=4909, actor_id="1",
                session_id="competing-owner",
            ) == "abandon"
        else:
            with pytest.raises(QaPlanExecutionStateError, match="requires_steering"):
                plan_execution_abort_authority(
                    test_db, stored, item_id=4909, actor_id="1",
                    session_id="competing-owner",
                )
        return

    stored = select_plan_execution(test_db, execution["id"], lock=False)
    assert stored["state"] == ("aborted" if abandoned else state)
    assert stored["release_reason"] == ("stale-heartbeat" if abandoned else None)


def test_missing_session_evidence_does_not_abandon_a_waiting_walk(test_db):
    assert not plan_execution_is_abandoned(
        test_db, {"state": "waiting", "session_id": "missing", "heartbeat_at": OLD},
    )
