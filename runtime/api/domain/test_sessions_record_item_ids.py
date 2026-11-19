"""Session focus writers bind ``items.id`` integers.

A non-numeric id refuses with ``INVALID_ITEM_ID`` before any statement
runs, so a caller sharing the connection (item writes record attribution
on their own transaction) keeps a usable transaction.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.session_holdings import insert_session
from yoke_core.domain.sessions_analytics import SessionError
from yoke_core.domain.sessions_render_attribution import (
    get_session_attribution,
    record_recent_item,
    set_current_item,
)

SESSION = "sess-item-ids"


@pytest.fixture
def session(test_db):
    insert_session(test_db, SESSION)
    return test_db


def test_writers_store_integer_ids(session):
    set_current_item(session, SESSION, "0042")
    record_recent_item(session, SESSION, 7)

    attribution = get_session_attribution(session, SESSION)
    assert attribution["current_item_id"] == 42
    assert attribution["recent_item_id"] == 7


@pytest.mark.parametrize("writer", [set_current_item, record_recent_item])
def test_non_numeric_id_refuses_before_sql_and_keeps_the_transaction(session, writer):
    session.execute(
        "UPDATE harness_sessions SET current_item_id = 9 WHERE session_id = %s",
        (SESSION,),
    )

    with pytest.raises(SessionError) as refused:
        writer(session, SESSION, "STRATEGIZE", commit=False)

    assert refused.value.code == "INVALID_ITEM_ID"
    # The open transaction is still usable: its uncommitted write is
    # visible and commits.
    session.commit()
    assert get_session_attribution(session, SESSION)["current_item_id"] == 9
