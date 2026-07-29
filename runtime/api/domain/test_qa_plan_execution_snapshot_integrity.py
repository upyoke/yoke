"""Read-time integrity checks for immutable QA execution snapshots."""

from __future__ import annotations

from copy import deepcopy

import pytest

from runtime.api.domain.test_qa_plan_execution_authority import (
    _materialize_two_cases,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_execution_environment_target import target_digest
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_execution_store import (
    QaPlanExecutionStateError,
    canonical,
    roster_digest,
    select_plan_execution,
)


@pytest.mark.parametrize(
    ("tamper", "lock", "message"),
    (
        ("roster", False, "roster snapshot digest"),
        ("target", True, "roster target does not match"),
    ),
)
def test_select_rejects_persisted_snapshot_tampering(
    tamper: str,
    lock: bool,
    message: str,
) -> None:
    with test_database() as conn:
        _materialize_two_cases(conn, item_id=4540)
        execution = begin_plan_execution(
            conn,
            item_id=4540,
            transition_id="implemented",
            actor_id="7",
            session_id="snapshot-integrity",
        )
        roster = deepcopy(execution["roster"])
        digest = str(execution["roster_digest"])
        if tamper == "roster":
            roster[0]["case_key"] = "tampered-case"
        else:
            changed_target = deepcopy(execution["execution_target"])
            changed_target["environment"]["name"] = "tampered"
            changed_digest = target_digest(changed_target)
            for case in roster:
                case["execution_target"] = changed_target
                case["execution_target_digest"] = changed_digest
            digest = roster_digest(roster)
        conn.execute(
            "UPDATE qa_plan_executions SET roster_json=%s,roster_digest=%s WHERE id=%s",
            (canonical(roster), digest, execution["id"]),
        )
        conn.commit()

        with pytest.raises(QaPlanExecutionStateError, match=message):
            select_plan_execution(conn, str(execution["id"]), lock=lock)
