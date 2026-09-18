"""``item_worktrees.inventory`` — the project-wide lane read.

This read exists so a machine holding a checkout can decide lane hygiene
without local SQL, which is the only way the worktree-health check can run
for a project that relays to its control plane over https. The cases below
pin the three properties that decision depends on: released lanes are
included, the answer carries the owning item's terminal state and the
project's target branch, and an unknown project refuses rather than
reporting an empty inventory a caller would read as "nothing to retire".
"""

from __future__ import annotations

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.handlers import item_worktree_inventory


def _request(payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="item_worktrees.inventory",
        actor=ActorContext(actor_id="1", session_id="caller"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


class _KeepOpenConn:
    """Keep the handler's ``with connect()`` from closing the test's conn."""

    def __init__(self, conn):
        self._conn = conn

    def __enter__(self):
        return self._conn

    def __exit__(self, *exc):
        return False


def _seeded_universe():
    """One project, one done item with a released lane, one live item."""
    name = pg_testdb.create_test_database()
    conn = pg_testdb.drop_database_on_close(pg_testdb.connect_test_database(name), name)
    apply_fixture_ddl(
        conn,
        "CREATE TABLE projects (id INTEGER, slug TEXT, name TEXT, "
        "public_item_prefix TEXT, default_branch TEXT, org_id INTEGER)",
    )
    apply_fixture_ddl(
        conn,
        "CREATE TABLE items (id INTEGER, project_id INTEGER, status TEXT, "
        "project_sequence INTEGER)",
    )
    apply_fixture_ddl(
        conn,
        "CREATE TABLE item_worktrees (id INTEGER, item_id INTEGER, branch TEXT, "
        "path TEXT, lane_role TEXT, state TEXT)",
    )
    conn.execute(
        "INSERT INTO projects (id, slug, name, public_item_prefix, default_branch) "
        "VALUES (7, 'platform', 'Platform', 'PLAT', 'main')"
    )
    conn.execute(
        "INSERT INTO items (id, project_id, status, project_sequence) "
        "VALUES (70, 7, 'done', 139), (71, 7, 'implementing', 141)"
    )
    conn.execute(
        "INSERT INTO item_worktrees (id, item_id, branch, path, lane_role, state) "
        "VALUES (1, 70, 'PLAT-139', '/repo/.worktrees/PLAT-139', "
        "'implementation', 'released'), "
        "(2, 71, 'PLAT-141', '/repo/.worktrees/PLAT-141', "
        "'implementation', 'active')"
    )
    conn.commit()
    return conn


def _lanes_by_branch(payload):
    return {lane["branch"]: lane for lane in payload["lanes"]}


def test_inventory_includes_released_lanes_with_owner_state(monkeypatch) -> None:
    """A released row is the residue a caller is hunting, so it must appear."""
    conn = _seeded_universe()
    monkeypatch.setattr(db_helpers, "connect", lambda: _KeepOpenConn(conn))

    outcome = item_worktree_inventory.handle_inventory(_request({"project": "platform"}))

    assert outcome.primary_success
    lanes = _lanes_by_branch(outcome.result_payload)
    assert set(lanes) == {"PLAT-139", "PLAT-141"}
    retired = lanes["PLAT-139"]
    assert retired["status"] == "done"
    assert retired["state"] == "released"
    assert retired["target_branch"] == "main"
    assert retired["path"] == "/repo/.worktrees/PLAT-139"
    assert retired["item_id"] == 70
    assert lanes["PLAT-141"]["status"] == "implementing"


def test_inventory_resolves_a_project_by_numeric_id(monkeypatch) -> None:
    """Machine checkout mappings often yield an id string, not a slug."""
    conn = _seeded_universe()
    monkeypatch.setattr(db_helpers, "connect", lambda: _KeepOpenConn(conn))

    outcome = item_worktree_inventory.handle_inventory(_request({"project": "7"}))

    assert outcome.primary_success
    assert set(_lanes_by_branch(outcome.result_payload)) == {"PLAT-139", "PLAT-141"}


def test_unknown_project_refuses_rather_than_reporting_no_lanes(monkeypatch) -> None:
    """An empty inventory would read as "nothing to retire" and skip the work."""
    conn = _seeded_universe()
    monkeypatch.setattr(db_helpers, "connect", lambda: _KeepOpenConn(conn))

    outcome = item_worktree_inventory.handle_inventory(_request({"project": "absent"}))

    assert not outcome.primary_success
    assert outcome.error is not None
    assert outcome.error.code == "project_not_found"


def test_missing_project_is_a_payload_refusal(monkeypatch) -> None:
    conn = _seeded_universe()
    monkeypatch.setattr(db_helpers, "connect", lambda: _KeepOpenConn(conn))

    outcome = item_worktree_inventory.handle_inventory(_request({}))

    assert not outcome.primary_success
    assert outcome.error is not None
    assert outcome.error.code == "payload_invalid"
