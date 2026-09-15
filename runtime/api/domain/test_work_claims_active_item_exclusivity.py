"""The DB-enforced facts a claim-scoped write (e.g. deployment_flow's
resolve-and-freeze) leans on instead of a bespoke CAS/versioning scheme:
at most one live claim exists per item, and writing an item scalar
requires holding it.
"""

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers.items_scalar import REGISTRATIONS
from yoke_core.domain.work_claim_targets import make_item_target


def _session(conn: Any, session_id: str) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id,executor,provider,model,execution_lane,workspace,project_id,"
        "mode,offered_at,last_heartbeat) VALUES "
        "(%s,'codex','openai','test','primary',%s,1,'wait',%s,%s)",
        (session_id, f"/tmp/{session_id}", now, now),
    )
    conn.commit()


def _claim(conn: Any, *, session_id: str, item_id: int) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO work_claims (session_id,target_kind,scope,claimed_at,"
        "last_heartbeat) VALUES (%s,'item',%s,%s,%s)",
        (session_id, make_item_target(item_id).scope_json(), now, now),
    )


def test_items_scalar_update_requires_the_item_claim() -> None:
    """The registered guardrail this item's freeze docstring relies on."""
    entry = REGISTRATIONS[0]
    assert entry["function_id"] == "items.scalar.update"
    assert entry["claim_required_kind"] == "item"
    assert "claim_required" in entry["guardrails"]


def test_at_most_one_live_claim_can_exist_per_item(test_db: Any) -> None:
    """The DB refuses a second live item claim, not just application code."""
    item_id = 9801
    insert_item(test_db, id=item_id, project_sequence=item_id, workflow_id="issue")
    _session(test_db, "sess-first")
    _session(test_db, "sess-second")
    _claim(test_db, session_id="sess-first", item_id=item_id)
    test_db.commit()

    with pytest.raises(psycopg.errors.UniqueViolation):
        _claim(test_db, session_id="sess-second", item_id=item_id)
    test_db.rollback()

    # Releasing the first claim frees the item for a new live claim.
    test_db.execute(
        "UPDATE work_claims SET released_at=%s WHERE session_id=%s",
        (iso8601_now(), "sess-first"),
    )
    test_db.commit()
    _claim(test_db, session_id="sess-second", item_id=item_id)
    test_db.commit()
