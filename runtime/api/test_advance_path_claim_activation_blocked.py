"""Blocked-branch tests for the auto-activate path-claim phase.

Sibling of :mod:`test_advance_path_claim_activation`. Pins the behavior of
``run_activation_phase`` when a downstream item is ``state='blocked'`` and
the upstream is held by a real activation-edge claim, so the block must
survive the coord-only repair pass at activation entry.

Fixtures and seed helpers are duplicated rather than shared via
``runtime/api/conftest.py`` because that conftest is in scope for every test
under ``runtime/api/`` and the blast radius of widening it is worse than the
duplication cost here. Kept in its own module so the parent
``test_advance_path_claim_activation`` file stays under the file-line gate.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import advance_path_claim_activation as _module
from yoke_core.domain import db_backend
from yoke_core.domain.advance_path_claim_activation import (
    run_activation_phase,
)
from yoke_core.domain.actors import seed_canonical_actors, seed_human_actor
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_path_claim_tables,
)
from yoke_core.domain.schema_init_apply import execute_schema_script
from yoke_core.domain.schema_init_path_tables import (
    create_path_registry_tables,
)
from yoke_core.domain.schema_init_tables import create_core_tables


@pytest.fixture
def conn(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    config_path = tmp_path / "config.json"
    config_path.write_text(
        json.dumps({"projects": {str(repo_root): {"project_id": 1}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("YOKE_MACHINE_CONFIG_FILE", str(config_path))
    name = pg_testdb.create_test_database()
    monkeypatch.setenv(
        db_backend.PG_DSN_ENV, pg_testdb.dsn_for_test_database(name)
    )
    c = pg_testdb.connect_test_database(name)
    create_core_tables(c)
    create_path_registry_tables(c)
    create_actor_path_claim_tables(c)
    seed_canonical_actors(c)
    c.execute(
        "INSERT INTO projects (id, slug, name, created_at) "
        "VALUES (1, 'yoke', 'yoke', '2026-05-01T00:00:00Z')"
    )
    c.execute(
        "INSERT INTO path_snapshots (project_id, commit_sha, built_at) "
        "VALUES (1, 'snap-base', '2026-05-01T00:00:00Z')"
    )
    c.commit()
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


def _seed_item(conn, *, item_id: int = 9001) -> int:
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    conn.commit()
    return item_id


def _seed_target(conn, path_string: str = "runtime/api/domain") -> int:
    cur = conn.execute(
        "INSERT INTO path_targets "
        "(project_id, kind, path_string, generation, created_at) "
        "VALUES (1, 'directory', %s, 1, '2026-05-01T00:00:00Z') "
        "RETURNING id",
        (path_string,),
    )
    return int(cur.fetchone()[0])


def _seed_planned_claim(
    conn,
    *,
    item_id: int,
    actor_id: int,
    target_id: int,
    integration_target: str = "main",
) -> int:
    cur = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, actor_id, item_id, integration_target, registered_at) "
        "VALUES ('planned', 'exclusive', %s, %s, %s, "
        "'2026-05-01T00:00:00Z') RETURNING id",
        (actor_id, item_id, integration_target),
    )
    claim_id = int(cur.fetchone()[0])
    conn.execute(
        "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
        "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
        (claim_id, target_id),
    )
    conn.commit()
    return claim_id


def _set_state(conn, claim_id: int, state: str, blocked_reason=None):
    if blocked_reason is None:
        conn.execute(
            "UPDATE path_claims SET state = %s WHERE id = %s",
            (state, claim_id),
        )
    else:
        conn.execute(
            "UPDATE path_claims SET state = %s, blocked_reason = %s "
            "WHERE id = %s",
            (state, blocked_reason, claim_id),
        )
    conn.commit()


@pytest.fixture
def stub_resolver(monkeypatch):
    """Stub the integration-head resolver to return a deterministic SHA."""
    sha_holder = {"last": "snap-base"}

    def _stub(conn, *, project_id, repo_path, integration_target):
        return "snap-base"

    from yoke_core.domain import advance_path_claim_activation_retry as _retry
    monkeypatch.setattr(
        _retry,
        "resolve_integration_head_with_divergence_check",
        _stub,
    )
    return sha_holder


def _seed_real_upstream_block(conn, *, downstream_item_id, target_id):
    """Seed an active upstream claim on the same target with a real
    activation dep edge so the downstream's blocked state survives the
    coord-only repair pass.
    """
    upstream_actor = seed_human_actor(conn)
    upstream_item_id = downstream_item_id - 100
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'upstream', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (upstream_item_id, upstream_item_id),
    )
    cur = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, actor_id, item_id, integration_target, "
        "registered_at, activated_at, base_commit_sha) "
        "VALUES ('active', 'exclusive', %s, %s, 'main', "
        "'2026-05-01T00:00:00Z', '2026-05-01T01:00:00Z', 'snap-base') "
        "RETURNING id",
        (upstream_actor, upstream_item_id),
    )
    upstream_claim = int(cur.fetchone()[0])
    conn.execute(
        "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
        "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
        (upstream_claim, target_id),
    )
    execute_schema_script(
        conn,
        "CREATE TABLE IF NOT EXISTS item_dependencies ("
        "id INTEGER PRIMARY KEY, dependent_item TEXT NOT NULL, "
        "blocking_item TEXT NOT NULL, "
        "gate_point TEXT NOT NULL DEFAULT 'activation', "
        "satisfaction TEXT NOT NULL DEFAULT 'status:done', "
        "source TEXT NOT NULL, session_id INTEGER, "
        "rationale TEXT NOT NULL DEFAULT '', "
        "evidence_json TEXT NOT NULL DEFAULT '{}', "
        "created_at TEXT NOT NULL)",
    )
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item, blocking_item, "
        "gate_point, source, created_at) "
        "VALUES (%s, %s, 'activation', 'test', '2026-05-01T00:00:00Z')",
        (f"YOK-{downstream_item_id}", f"YOK-{upstream_item_id}"),
    )
    conn.commit()
    return upstream_claim


class TestBlocked:
    def test_blocked_claim_surfaces_error(self, conn, stub_resolver):
        # A real activation-edge upstream claim must exist so the block
        # survives the coord-only repair pass at activation entry.
        actor = seed_human_actor(conn)
        item_id = _seed_item(conn)
        target_id = _seed_target(conn)
        claim_id = _seed_planned_claim(
            conn, item_id=item_id, actor_id=actor,
            target_id=target_id,
        )
        upstream_claim = _seed_real_upstream_block(
            conn, downstream_item_id=item_id, target_id=target_id,
        )
        _set_state(
            conn, claim_id, "blocked",
            blocked_reason=(
                f"serial-via-dependency on path_claims.id={upstream_claim}"
            ),
        )
        result = run_activation_phase(
            conn, item_id=item_id, actor_id=actor,
        )
        assert result.is_blocked is True
        assert any("blocked" in m for m in result.blocked_errors)
        # Did not advance state.
        state = conn.execute(
            "SELECT state FROM path_claims WHERE id = %s", (claim_id,),
        ).fetchone()[0]
        assert state == "blocked"

    def test_blocked_message_names_upstream(self, conn, stub_resolver):
        actor = seed_human_actor(conn)
        item_id = _seed_item(conn)
        target_id = _seed_target(conn)
        claim_id = _seed_planned_claim(
            conn, item_id=item_id, actor_id=actor,
            target_id=target_id,
        )
        upstream_claim = _seed_real_upstream_block(
            conn, downstream_item_id=item_id, target_id=target_id,
        )
        _set_state(
            conn, claim_id, "blocked",
            blocked_reason=(
                f"serial-via-dependency on path_claims.id={upstream_claim}"
            ),
        )
        result = run_activation_phase(
            conn, item_id=item_id, actor_id=actor,
        )
        message = result.blocked_errors[0]
        assert str(upstream_claim) in message
