"""A freshly born universe registers actor-bound sessions that can claim paths.

The failure this covers was found on a clean-room install: every session
on it — hook-registered, ``yoke sessions begin``, every harness — stored
``actor_id`` NULL, so the first path-claim registration refused and no
item could reach a worktree. Nothing about the install was broken except
the binding: the human actor the universe was born with was sitting in
``actors`` the whole time.

So the coverage runs the public path end to end on a universe seeded
exactly the way ``schema_init.cmd_init`` seeds a real one: register
through :func:`begin_session` (the shared core under both the operator
command and the hook-driven registrar), then register a path claim as
that session with no explicit actor anywhere in the call.

The same path carries the grant convergence, because binding an actor
that holds no org role only moves the refusal one step later. A universe
born before the grant existed and upgraded in place arrives here exactly
that way, so registration is where it catches up.
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout

import pytest

from runtime.api.fixtures.backlog import seed_test_canonical_actors
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)
from runtime.api.test_constants import TEST_MODEL_ID
from yoke_core.api.service_client_sessions_lifecycle_begin import begin_session
from yoke_core.domain.local_operating_actor import holds_org_admin
from yoke_core.domain.path_claims_dispatch import cmd_register
from yoke_core.domain.sessions import claim_work


_ITEM_ID = 40501
_SESSION_ID = "fresh-universe-session"


@pytest.fixture
def fresh_universe(tmp_path, monkeypatch):
    """A born universe: canonical actors, one project, one claimable item."""
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        # The claim surfaces resolve the CALLER from ambient identity, so the
        # test process speaks as the session it just registered.
        monkeypatch.setenv("YOKE_SESSION_ID", _SESSION_ID)
        conn = connect_test_db(db_path)
        try:
            seed_test_canonical_actors(conn)
            conn.execute(
                "INSERT INTO projects (id, slug, name, github_repo, "
                "default_branch, public_item_prefix, created_at) "
                "VALUES (1, 'yoke', 'yoke', '', 'main', 'YOK', "
                "'2026-05-01T00:00:00Z') "
                "ON CONFLICT(id) DO UPDATE SET slug=excluded.slug"
            )
            conn.execute(
                "INSERT INTO items (id, title, workflow_id, workflow_version_id, "
                "status, priority, created_at, updated_at, project_id, "
                "project_sequence) VALUES "
                f"({_ITEM_ID}, 'fresh install claim', 'issue', "
                "(SELECT current_version_id FROM workflows WHERE id='issue'), "
                "'idea', 'medium', '2026-05-01T00:00:00Z', "
                f"'2026-05-01T00:00:00Z', 1, {_ITEM_ID})"
            )
            conn.commit()
            yield conn
        finally:
            conn.close()


def _begin(db) -> dict:
    return begin_session(
        db,
        session_id=_SESSION_ID,
        executor="claude-code",
        provider="anthropic",
        model=TEST_MODEL_ID,
        workspace="/tmp/fresh-universe",
        project_id=1,
    )


def _human_actor_id(db) -> int:
    return int(
        db.execute(
            "SELECT id FROM actors WHERE kind = 'human' ORDER BY id LIMIT 1"
        ).fetchone()[0]
    )


def test_public_registration_binds_the_installs_operating_actor(fresh_universe):
    conn = fresh_universe
    result = _begin(conn)
    assert result["success"] is True
    stored = conn.execute(
        "SELECT actor_id FROM harness_sessions WHERE session_id = %s",
        (_SESSION_ID,),
    ).fetchone()["actor_id"]
    assert stored == _human_actor_id(conn)


def test_path_claim_registration_succeeds_on_a_fresh_universe(fresh_universe):
    """The leg that was unreachable: claiming a path as the bound session."""
    conn = fresh_universe
    _begin(conn)
    claim_work(conn, session_id=_SESSION_ID, item_id=str(_ITEM_ID), reason="claim")

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cmd_register(
            [
                "--item",
                f"YOK-{_ITEM_ID}",
                "--integration-target",
                "main",
                "--paths",
                "src/fresh_install.py",
                "--allow-planned",
                "--session-id",
                _SESSION_ID,
            ]
        )
    payload = json.loads(out.getvalue() or err.getvalue())
    assert rc == 0, payload
    assert payload["success"] is True
    registered_by = conn.execute(
        "SELECT registered_by_actor_id FROM path_claims WHERE owner_item_id = %s",
        (_ITEM_ID,),
    ).fetchone()["registered_by_actor_id"]
    assert registered_by == _human_actor_id(conn)


def _strip_org_grant(db) -> int:
    """Model a universe born by an engine that predated the grant."""
    actor_id = _human_actor_id(db)
    db.execute("DELETE FROM actor_org_roles WHERE actor_id = %s", (actor_id,))
    db.commit()
    assert not holds_org_admin(db, actor_id)
    return actor_id


def test_registration_converges_the_grant_an_upgrade_left_missing(fresh_universe):
    conn = fresh_universe
    actor_id = _strip_org_grant(conn)

    assert _begin(conn)["success"] is True

    assert holds_org_admin(conn, actor_id)


def test_claiming_works_on_a_universe_upgraded_without_the_grant(fresh_universe):
    """The leg the walk could not reach: claim and path-register after upgrade."""
    conn = fresh_universe
    _strip_org_grant(conn)
    _begin(conn)

    claim_work(conn, session_id=_SESSION_ID, item_id=str(_ITEM_ID), reason="claim")

    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = cmd_register(
            [
                "--item",
                f"YOK-{_ITEM_ID}",
                "--integration-target",
                "main",
                "--paths",
                "src/upgraded_universe.py",
                "--allow-planned",
                "--session-id",
                _SESSION_ID,
            ]
        )
    payload = json.loads(out.getvalue() or err.getvalue())
    assert rc == 0, payload
    assert payload["success"] is True


def test_an_explicit_actor_converges_nothing(fresh_universe):
    """The bearer-token path belongs to universes that bootstrap their own."""
    conn = fresh_universe
    actor_id = _strip_org_grant(conn)

    result = begin_session(
        conn,
        session_id="explicit-actor-session",
        executor="claude-code",
        provider="anthropic",
        model=TEST_MODEL_ID,
        workspace="/tmp/fresh-universe",
        project_id=1,
        actor_id=actor_id,
    )

    assert result["success"] is True
    assert not holds_org_admin(conn, actor_id)
