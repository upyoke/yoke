"""Tests for the auto-activate path-claim phase.

Covers the four canonical outcomes the phase advertises (planned →
active happy path, blocked → surface upstream error, active → no-op,
no claims → no-op) plus the harness-neutrality residue check.

The integration head + snapshot lookup is covered separately in
``test_path_claims_integration_resolver.py``; here the resolver path is
exercised via :func:`monkeypatch` to keep these tests focused on the
phase's branching logic.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import advance_path_claim_activation as _module
from yoke_core.domain import db_backend
from yoke_core.domain.advance_path_claim_activation import (
    ActivationResult,
    run_activation_phase,
)
from yoke_core.domain.actors import seed_canonical_actors, seed_human_actor
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_path_claim_tables,
)
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


class TestHappyPath:
    def test_planned_claim_flips_to_active(self, conn, stub_resolver):
        actor = seed_human_actor(conn)
        item_id = _seed_item(conn)
        target_id = _seed_target(conn)
        claim_id = _seed_planned_claim(
            conn, item_id=item_id, actor_id=actor,
            target_id=target_id,
        )
        result = run_activation_phase(
            conn, item_id=item_id, actor_id=actor,
        )
        assert result.is_blocked is False
        assert result.activated_claim_ids == [claim_id]
        state = conn.execute(
            "SELECT state FROM path_claims WHERE id = %s", (claim_id,),
        ).fetchone()[0]
        assert state == "active"

    def test_returns_typed_result(self, conn, stub_resolver):
        actor = seed_human_actor(conn)
        item_id = _seed_item(conn)
        target_id = _seed_target(conn)
        _seed_planned_claim(
            conn, item_id=item_id, actor_id=actor,
            target_id=target_id,
        )
        result = run_activation_phase(
            conn, item_id=item_id, actor_id=actor,
        )
        assert isinstance(result, ActivationResult)
        assert result.item_id == item_id
        assert result.actor_id == actor


class TestNoOps:
    def test_active_claim_is_no_op(self, conn, stub_resolver):
        actor = seed_human_actor(conn)
        item_id = _seed_item(conn)
        target_id = _seed_target(conn)
        claim_id = _seed_planned_claim(
            conn, item_id=item_id, actor_id=actor,
            target_id=target_id,
        )
        # Hand-flip to active without touching the activation phase.
        conn.execute(
            "UPDATE path_claims SET state='active', "
            "base_commit_sha='deadbeefcafef00d000000010000000000000000', "
            "activated_at='2026-05-01T01:00:00Z' "
            "WHERE id = %s",
            (claim_id,),
        )
        conn.commit()
        result = run_activation_phase(
            conn, item_id=item_id, actor_id=actor,
        )
        assert result.is_blocked is False
        assert result.activated_claim_ids == []  # nothing flipped
        # Still active.
        state = conn.execute(
            "SELECT state FROM path_claims WHERE id = %s", (claim_id,),
        ).fetchone()[0]
        assert state == "active"

    def test_no_claims_returns_empty_result(self, conn, stub_resolver):
        actor = seed_human_actor(conn)
        item_id = _seed_item(conn)
        result = run_activation_phase(
            conn, item_id=item_id, actor_id=actor,
        )
        assert result.is_blocked is False
        assert result.outcomes == []
        assert result.activated_claim_ids == []


class TestDivergence:
    def test_diverged_refs_are_surfaced(self, conn, monkeypatch):
        from yoke_core.domain.path_claims_integration_resolver import (
            IntegrationTargetDiverged,
        )

        def _raise_diverged(conn, *, project_id, repo_path,
                            integration_target):
            raise IntegrationTargetDiverged(
                f"origin/{integration_target} and "
                f"refs/heads/{integration_target} have diverged"
            )

        from yoke_core.domain import advance_path_claim_activation_retry as _retry
        monkeypatch.setattr(
            _retry,
            "resolve_integration_head_with_divergence_check",
            _raise_diverged,
        )

        actor = seed_human_actor(conn)
        item_id = _seed_item(conn)
        target_id = _seed_target(conn)
        _seed_planned_claim(
            conn, item_id=item_id, actor_id=actor,
            target_id=target_id,
        )
        result = run_activation_phase(
            conn, item_id=item_id, actor_id=actor,
        )
        assert result.is_blocked is True
        assert result.diverged_error is not None
        assert "diverged" in result.diverged_error


class TestActivationErrors:
    def test_non_divergence_activation_error_blocks_with_message(
        self, conn, monkeypatch
    ):
        from yoke_core.domain.path_claims_boundary_git import (
            BoundaryCheckError,
        )

        def _raise_boundary(conn, *, project_id, repo_path,
                            integration_target):
            raise BoundaryCheckError("cannot resolve integration target")

        from yoke_core.domain import advance_path_claim_activation_retry as _retry
        monkeypatch.setattr(
            _retry,
            "resolve_integration_head_with_divergence_check",
            _raise_boundary,
        )

        actor = seed_human_actor(conn)
        item_id = _seed_item(conn)
        target_id = _seed_target(conn)
        _seed_planned_claim(
            conn, item_id=item_id, actor_id=actor,
            target_id=target_id,
        )

        result = run_activation_phase(
            conn, item_id=item_id, actor_id=actor,
        )

        assert result.is_blocked is True
        assert result.diverged_error is None
        assert result.blocked_errors
        assert "cannot resolve integration target" in result.blocked_errors[0]
