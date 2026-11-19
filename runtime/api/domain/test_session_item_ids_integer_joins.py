"""The planning-phase readers join ``items.id`` to the session focus column.

Both columns are INTEGER on the real schema, so on Postgres the join
returns the session's current item instead of an "integer = text" error
the readers used to swallow into ``None`` (which denied planning sessions
their dispatch-inputs scratch writes).
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.session_holdings import insert_session
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.handlers import claims_work_holders
from yoke_core.domain.path_claim_bash_parser_planning_phase import (
    session_is_planning_phase,
)

PLANNING = "sess-planning"
IMPLEMENTING = "sess-implementing"


class _KeepOpen:
    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *exc):
        return False


@pytest.fixture
def focused(test_db):
    insert_item(test_db, id=5101, workflow_id="dash", status="idea")
    insert_item(test_db, id=5102, workflow_id="dash", status="implementing")
    insert_session(test_db, PLANNING, current_item_id=5101)
    insert_session(test_db, IMPLEMENTING, current_item_id=5102)
    return test_db


def _holder_list(conn, monkeypatch, session_id):
    monkeypatch.setattr(db_helpers, "connect", lambda: _KeepOpen(conn))
    outcome = claims_work_holders.handle_holder_list(
        FunctionCallRequest(
            function="claims.work.holder_list",
            actor=ActorContext(actor_id="1", session_id=session_id),
            target=TargetRef(kind="global"),
            payload={"session_id": session_id},
        )
    )
    assert outcome.primary_success, outcome.error
    return outcome.result_payload["current_item_before_implementation"]


def test_holder_list_reports_a_pre_implementation_focus(focused, monkeypatch):
    assert _holder_list(focused, monkeypatch, PLANNING) is True
    assert _holder_list(focused, monkeypatch, IMPLEMENTING) is False


def test_bash_guard_sees_the_planning_session(focused):
    assert session_is_planning_phase(session_id=PLANNING, conn=focused) is True
    assert session_is_planning_phase(session_id=IMPLEMENTING, conn=focused) is False


def test_the_join_itself_runs_on_the_real_schema(focused):
    row = focused.execute(
        "SELECT i.id, i.status FROM harness_sessions hs "
        "JOIN items i ON i.id = hs.current_item_id WHERE hs.session_id = %s",
        (PLANNING,),
    ).fetchone()
    assert (row[0], row[1]) == (5101, "idea")
