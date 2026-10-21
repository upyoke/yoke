"""Tests for the read-only actors lookup CLI.

Exercises ``cmd_actors_list`` and ``cmd_actors_get`` end-to-end via a
backend-aware fixture DB so the canonical resolver picks it up. The
``test_db`` in-memory fixture would not work here — the cmd opens
its own connection via ``db_helpers.connect`` rather than accepting one,
so the fixture must seed the same backend-resolved DB the cmd reads
(``YOKE_DB`` file on SQLite, the repointed ``YOKE_PG_DSN``
disposable per-test DB on Postgres).
"""

from __future__ import annotations

import io
import json
from contextlib import redirect_stderr, redirect_stdout

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.actors import seed_human_actor, seed_system_actor, set_actor_name
from runtime.api.fixtures.backlog import seed_test_canonical_human
from runtime.api.fixtures.file_test_db import (
    apply_test_schema,
    init_test_db,
    seeded_schema,
)
from yoke_core.api.service_client_actors import cmd_actors_get, cmd_actors_list

SYSTEM_COMPONENT = "test-component"


def _seed_actors_fixture() -> None:
    """Seed the canonical human and one named system actor for lookup tests."""
    conn = db_backend.connect()
    try:
        seed_test_canonical_human(conn)
        seed_system_actor(conn, SYSTEM_COMPONENT)
        conn.commit()
    finally:
        conn.close()


_apply_actors_fixture_schema = seeded_schema(apply_test_schema, _seed_actors_fixture)


@pytest.fixture
def actors_db(tmp_path, monkeypatch):
    """Backend-aware temp DB with full schema + canonical actors seeded.

    SQLite: a real file under ``tmp_path``; ``YOKE_DB`` points the cmd's
    connection factory at it. Postgres: a disposable per-test database with
    ``YOKE_PG_DSN`` repointed for the fixture's lifetime so the seed and the
    factory-routed cmd hit the same DB. ``YOKE_DB`` is set inside the context
    on both engines (the Postgres factory ignores the path in favor of the DSN).
    """
    with init_test_db(tmp_path, apply_schema=_apply_actors_fixture_schema) as db_path:
        monkeypatch.setenv("YOKE_DB", str(db_path))
        yield str(db_path)


def _capture_stdout(func, *args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = func(*args)
    return rc, buf.getvalue()


def _capture_stderr(func, *args):
    buf = io.StringIO()
    with redirect_stderr(buf):
        rc = func(*args)
    return rc, buf.getvalue()


class TestActorsList:
    def test_list_returns_seeded_actors(self, actors_db):
        rc, stdout = _capture_stdout(cmd_actors_list, [])
        assert rc == 0
        payload = json.loads(stdout)
        # The fixture seeds the local human (ben) and one system actor.
        kinds = sorted(a["kind"] for a in payload)
        assert kinds == ["human", "system"]
        names = sorted(a["name"] for a in payload if a["name"])
        assert "ben" in names
        assert SYSTEM_COMPONENT in names

    def test_list_rejects_extra_args(self, actors_db):
        rc, stderr = _capture_stderr(cmd_actors_list, ["unexpected"])
        assert rc == 2
        assert "Usage" in stderr

    def test_list_empty_returns_array(self, tmp_path, monkeypatch):
        # Build a DB with empty actors table — schema only, no canonical seeding.
        with init_test_db(tmp_path, apply_schema=apply_test_schema) as db_path:
            monkeypatch.setenv("YOKE_DB", str(db_path))
            with db_backend.connect() as conn:
                conn.execute("TRUNCATE actors CASCADE")

            rc, stdout = _capture_stdout(cmd_actors_list, [])
            assert rc == 0
            assert json.loads(stdout) == []


class TestActorsGet:
    def test_get_returns_actor_with_name(self, actors_db):
        # First find the local human's id via the list command.
        _, list_out = _capture_stdout(cmd_actors_list, [])
        actors = json.loads(list_out)
        local_human = next(a for a in actors if a["name"] == "ben")

        rc, stdout = _capture_stdout(cmd_actors_get, [str(local_human["id"])])
        assert rc == 0
        payload = json.loads(stdout)
        assert payload["id"] == local_human["id"]
        assert payload["kind"] == "human"
        assert payload["name"] == "ben"

    def test_get_returns_the_current_name_after_a_rename(self, actors_db):
        conn = db_backend.connect()
        try:
            actor_id = seed_human_actor(conn, "Ben")
            set_actor_name(conn, actor_id, "Ben Bauman")
        finally:
            conn.close()

        rc, stdout = _capture_stdout(cmd_actors_get, [str(actor_id)])
        assert rc == 0
        payload = json.loads(stdout)
        assert payload["id"] == actor_id
        assert payload["name"] == "Ben Bauman"

    def test_get_returns_system_actor(self, actors_db):
        _, list_out = _capture_stdout(cmd_actors_list, [])
        actors = json.loads(list_out)
        system = next(a for a in actors if a["name"] == SYSTEM_COMPONENT)

        rc, stdout = _capture_stdout(cmd_actors_get, [str(system["id"])])
        assert rc == 0
        payload = json.loads(stdout)
        assert payload["kind"] == "system"
        assert payload["system_component"] == SYSTEM_COMPONENT
        assert payload["name"] == SYSTEM_COMPONENT

    def test_get_unknown_id_returns_not_found(self, actors_db):
        rc, stderr = _capture_stderr(cmd_actors_get, ["424242"])
        assert rc == 1
        err = json.loads(stderr)
        assert err == {"error": "not_found", "id": 424242}

    def test_get_invalid_id_returns_2(self, actors_db):
        rc, stderr = _capture_stderr(cmd_actors_get, ["not-an-int"])
        assert rc == 2
        err = json.loads(stderr)
        assert err == {"error": "invalid_id", "value": "not-an-int"}

    def test_get_missing_args_returns_2(self, actors_db):
        rc, stderr = _capture_stderr(cmd_actors_get, [])
        assert rc == 2
        assert "Usage" in stderr
