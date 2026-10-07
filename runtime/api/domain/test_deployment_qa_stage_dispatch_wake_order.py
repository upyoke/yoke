"""An item-QA stage wakes waiting owners before closing settled members.

Closing a member with nothing to check runs its whole close-out, GitHub
sync included. Done inline per member, every owner later in the walk sat
unwoken behind those close-outs, indistinguishable from a missing wake.
The stage now sends every owner wake first and closes members after.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from yoke_core.domain import deployment_qa_stage_dispatch as dispatch
from yoke_core.domain import deployment_qa_stage_gate as gate


RUN_ID = "run-20261007-024"
STAGE = {"name": "item-qa", "scope": "item"}
SETTLED_MEMBER = 101
WAITING_MEMBER = 202


class _Rows:
    def __init__(self, one: Any = None, many: list | None = None) -> None:
        self._one, self._many = one, many or []

    def fetchone(self) -> Any:
        return self._one

    def fetchall(self) -> list:
        return self._many


class _Conn:
    """Answers the three reads the stage walk makes before gating."""

    def __init__(self) -> None:
        self.commits = 0

    def execute(self, sql: str, params: tuple = ()) -> _Rows:
        if "FROM deployment_runs" in sql:
            return _Rows(one=(1, "persistent", "a" * 40))
        if "FROM deployment_run_items" in sql:
            return _Rows(many=[(SETTLED_MEMBER,), (WAITING_MEMBER,)])
        return _Rows(one=(1,))  # every member already has materialized cases

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass


def _status(conn, *, run_id, stage_name, member_item_id, notify_acceptance=True):
    assert notify_acceptance is False
    if member_item_id == SETTLED_MEMBER:
        return {"accepted": True, "reasons": [], "outcome": "discharged"}
    return {
        "accepted": False,
        "reasons": ["no completed scoped QA execution exists"],
        "outcome": "waiting",
    }


def test_owner_wakes_go_out_before_any_member_close_out() -> None:
    events: list[tuple[str, int]] = []
    conn = _Conn()
    with (
        patch.object(gate, "deployment_qa_stage_status", side_effect=_status),
        patch.object(dispatch, "report_stage_result"),
        patch.object(
            dispatch,
            "notify_item_scoped_qa_wait",
            side_effect=lambda conn, **kw: (
                events.append(("wake", kw["item_id"])) or "delivered"
            ),
        ),
        patch(
            "yoke_core.domain.deployment_qa_member_acceptance_notice."
            "notify_item_qa_accepted",
            side_effect=lambda conn, **kw: events.append(("close", kw["item_id"])),
        ),
    ):
        code, message = dispatch.materialize_and_gate_deployment_qa_stage(
            conn, STAGE, run_id=RUN_ID
        )

    assert code == -4
    assert f"member {WAITING_MEMBER}" in message
    # The settled member sorts first, yet its close-out follows the wake.
    assert events == [("wake", WAITING_MEMBER), ("close", SETTLED_MEMBER)]
    assert conn.commits >= 2


def test_the_gate_leaves_acceptance_to_a_caller_that_defers_it() -> None:
    accepted = {"accepted": True, "reasons": []}
    with (
        patch.object(gate, "deployment_qa_stage_subject", return_value={}),
        patch.object(gate, "deployment_qa_execution_target", return_value={}),
        patch.object(gate.target_authority, "target_digest", return_value="d"),
        patch.object(gate, "_settle_stage_status", return_value=dict(accepted)),
        patch(
            "yoke_core.domain.deployment_qa_member_acceptance_notice."
            "notify_item_qa_accepted"
        ) as notify,
    ):
        kwargs = {"run_id": RUN_ID, "stage_name": "item-qa"}
        gate.deployment_qa_stage_status(
            None, member_item_id=SETTLED_MEMBER, notify_acceptance=False, **kwargs
        )
        notify.assert_not_called()
        gate.deployment_qa_stage_status(None, member_item_id=SETTLED_MEMBER, **kwargs)
        notify.assert_called_once()
