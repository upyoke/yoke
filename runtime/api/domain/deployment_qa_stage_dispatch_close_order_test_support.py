# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

from unittest.mock import patch

from yoke_contracts.public_ref import format_item_ref

from yoke_core.domain import deployment_qa_dispatch_wait_notice as wait_notice

from yoke_core.domain import deployment_qa_stage_dispatch as dispatch

from yoke_core.domain import deployment_qa_stage_gate as gate

RUN_ID = "run-20261007-024"

STAGE = {"name": "item-qa", "scope": "item"}

SETTLED_MEMBER = 101

WAITING_MEMBER = 202

PROJECT_SLUG = "sample"

PUBLIC_PREFIX = "SAMPLE"

MEMBER_SEQUENCES = {SETTLED_MEMBER: 11, WAITING_MEMBER: 12}


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
        self.rollbacks = 0

    def execute(self, sql: str, params: tuple = ()) -> _Rows:
        if "JOIN projects" in sql:
            return _Rows(
                many=[
                    (member, PROJECT_SLUG, PUBLIC_PREFIX, MEMBER_SEQUENCES[member])
                    for member in params
                ]
            )
        if "SELECT deployment_member_item_id,BOOL_OR(" in sql:
            return _Rows(many=[(SETTLED_MEMBER, False), (WAITING_MEMBER, False)])
        if "SELECT item_id FROM deployment_run_items" in sql:
            return _Rows(
                many=[{"item_id": SETTLED_MEMBER}, {"item_id": WAITING_MEMBER}]
            )
        if "SELECT slug FROM projects" in sql:
            return _Rows(one=(PROJECT_SLUG,))
        if "SELECT requirement_snapshot" in sql:
            return _Rows(one=("{}",))
        if "FROM deployment_runs" in sql:
            return _Rows(one=(1, "persistent", "a" * 40))
        if "FROM deployment_run_items" in sql:
            return _Rows(many=[(SETTLED_MEMBER,), (WAITING_MEMBER,)])
        return _Rows(one=(1,))  # every member already has materialized cases

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _status(conn, *, run_id, stage_name, member_item_id, notify_acceptance=True):
    assert notify_acceptance is False
    if member_item_id == SETTLED_MEMBER:
        return {"accepted": True, "reasons": [], "outcome": "discharged"}
    return {
        "accepted": False,
        "reasons": ["no completed scoped QA execution exists"],
        "outcome": "waiting",
    }
