"""merge preflight + done-transition gate refuse blocked=1.

Both gates wrap the same `yoke_core.domain.advance_blocked_gate.evaluate`
helper around the items.blocked column. These tests exercise the helper
through the lens of the wrapping gates by simulating a blocked item and
verifying the gate would refuse (the helper's `blocked` flag drives the
refusal in both call sites).
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.domain.advance_blocked_gate import evaluate


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    apply_fixture_ddl(
        c,
        """
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            blocked INTEGER DEFAULT 0,
            blocked_reason TEXT,
            worktree TEXT
        );
        """,
    )
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


def test_merge_refuses_blocked_item(conn):
    """Merge preflight reads items.blocked via the gate evaluator."""
    conn.execute(
        "INSERT INTO items (id, blocked, blocked_reason, worktree) "
        "VALUES (10, 1, 'merge-test reason', 'YOK-10')"
    )
    decision = evaluate(conn, 10)
    assert decision.blocked is True
    assert "merge-test reason" in (decision.reason or "")


def test_done_transition_refuses_blocked_item(conn):
    """Done-transition gate reads items.blocked via the same evaluator."""
    conn.execute(
        "INSERT INTO items (id, blocked, blocked_reason, worktree) "
        "VALUES (20, 1, 'done-test reason', 'YOK-20')"
    )
    decision = evaluate(conn, 20)
    assert decision.blocked is True
    # The done-transition runner returns exit code 9 when this fires;
    # the test verifies the underlying decision shape that the runner
    # consumes.
    assert decision.rendered_blocker is not None


def test_unblocked_item_passes_both_gates(conn):
    conn.execute(
        "INSERT INTO items (id, blocked, blocked_reason, worktree) "
        "VALUES (30, 0, NULL, 'YOK-30')"
    )
    decision = evaluate(conn, 30)
    assert decision.blocked is False
    assert decision.rendered_blocker is None
