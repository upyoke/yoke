"""Retiring a project preserves its name in current and released holdings."""

import pytest

from runtime.api.fixtures.session_holdings import (
    insert_document_lock,
    insert_session,
    insert_steering_claim,
    instant_ago,
)
from yoke_core.domain.sessions_list_read import list_sessions


@pytest.mark.parametrize("released", [False, True])
def test_retired_project_holdings_carry_their_own_slug(test_db, released):
    session_id = "retired-project-holder"
    insert_session(test_db, session_id)
    insert_steering_claim(test_db, session_id)
    insert_document_lock(test_db, session_id, 1, "MISSION")
    if released:
        test_db.execute(
            "UPDATE work_claims SET released_at=%s WHERE session_id=%s",
            (instant_ago(5), session_id),
        )
        test_db.execute(
            "UPDATE strategy_doc_claims SET released_at=%s WHERE owner_session_id=%s",
            (instant_ago(5), session_id),
        )
    test_db.execute("UPDATE projects SET retired_at=%s WHERE id=1", (instant_ago(),))
    slug = test_db.execute("SELECT slug FROM projects WHERE id=1").fetchone()[0]
    test_db.commit()

    row = next(row for row in list_sessions() if row["session_id"] == session_id)
    holdings = row["holdings"]["previous" if released else "current"]
    assert {holding["target_kind"] for holding in holdings} == {
        "steering", "strategy_document",
    }
    assert all(holding["project"] == slug for holding in holdings)
