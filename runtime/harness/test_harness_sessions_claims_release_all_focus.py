"""Regression test: legacy harness `release-all` clears current_item_id.

The CLI `release-all-claims` ends up in `cmd_release_all` via the
`harness_sessions release-all` subcommand. Prior to this fix, the bulk
UPDATE released every claim but left `harness_sessions.current_item_id`
pointing at the last-claimed item — the path-claim pre-edit guard read
that link and blocked subsequent edits with `worktree-unresolved`. This
test pins the parity fix so the legacy CLI matches the modern typed
release path.
"""

from __future__ import annotations

import pytest  # noqa: F401

from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from runtime.api.test_sessions import EMIT_PATH_TABLES, _register, conn  # noqa: F401
from runtime.harness.harness_sessions_claims import (
    cmd_claim,
    cmd_release_all,
)


def test_cmd_release_all_clears_current_item_id(conn):
    # cmd_claim emits WorkClaimed; the per-test DB needs the full events +
    # event_registry schema so the emit INSERT succeeds (a minimal events
    # table would fail the INSERT and poison the transaction on Postgres).
    apply_fixture_ddl(conn, EMIT_PATH_TABLES)
    _register(conn, session_id="sess-A")
    cmd_claim(conn, "sess-A", "item", item_id=4242)

    before = conn.execute(
        "SELECT current_item_id FROM harness_sessions WHERE session_id='sess-A'"
    ).fetchone()
    assert before["current_item_id"] == "4242"

    cmd_release_all(conn, "sess-A", reason="released")

    after = conn.execute(
        "SELECT current_item_id, recent_item_id FROM harness_sessions "
        "WHERE session_id='sess-A'"
    ).fetchone()
    assert after["current_item_id"] is None
    assert after["recent_item_id"] == "4242"
