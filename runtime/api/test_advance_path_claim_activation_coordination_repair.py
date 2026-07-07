"""Activation-phase repair of coordination_only mutex residue.

Sibling of :mod:`test_advance_path_claim_activation`. Pins the AC-12 / AC-14
behavior: the repair pass that fires before the per-claim activation loop
unblocks ``state='blocked'`` rows whose only inter-item edge is
``coordination_only``, while leaving rows with a real ``activation`` /
``integration`` / ``closure`` edge blocked.

Kept in its own module so the parent file stays under the file-line gate.
Fixtures and minimal seed helpers are duplicated rather than shared via the
broader ``runtime/api/conftest.py`` — the blast radius of a shared in-memory
schema fixture across all of ``runtime/api/`` is worse than the duplication
cost here.
"""

from __future__ import annotations

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
def conn(monkeypatch):
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
        "VALUES (1, 'yoke', 'yoke', "
        "'2026-05-01T00:00:00Z')"
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
    monkeypatch.setattr(
        _module,
        "checkout_for_project_id",
        lambda _project_id: "/tmp/yoke-checkout",
    )
    return sha_holder


def _ensure_dep_table(conn):
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
    conn.commit()


def _add_edge(conn, *, dependent: int, blocking: int, gate_point: str):
    _ensure_dep_table(conn)
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item, blocking_item, "
        "gate_point, source, created_at) "
        "VALUES (%s, %s, %s, 'test', '2026-05-01T00:00:00Z')",
        (f"YOK-{dependent}", f"YOK-{blocking}", gate_point),
    )
    conn.commit()


def _seed_active_claim(conn, *, item_id, actor_id, target_id) -> int:
    cur = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, actor_id, item_id, integration_target, "
        "registered_at, activated_at, base_commit_sha) "
        "VALUES ('active', 'exclusive', %s, %s, 'main', "
        "'2026-05-01T00:00:00Z', '2026-05-01T01:00:00Z', 'snap-base') "
        "RETURNING id",
        (actor_id, item_id),
    )
    cid = int(cur.fetchone()[0])
    conn.execute(
        "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
        "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
        (cid, target_id),
    )
    conn.commit()
    return cid


def _seed_blocked_claim(
    conn, *, item_id, actor_id, target_id, blocked_reason,
) -> int:
    cur = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, actor_id, item_id, integration_target, "
        "registered_at, blocked_reason) "
        "VALUES ('blocked', 'exclusive', %s, %s, 'main', "
        "'2026-05-01T00:00:00Z', %s) RETURNING id",
        (actor_id, item_id, blocked_reason),
    )
    cid = int(cur.fetchone()[0])
    conn.execute(
        "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
        "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
        (cid, target_id),
    )
    conn.commit()
    return cid


class TestCoordinationOnlyRepair:
    """Activation-phase repair of legacy coord-only mutex residue.

    Pins AC-12: ``state='blocked'`` rows whose only inter-item edge is
    ``coordination_only`` are repaired to ``state='planned'`` before
    the activation loop, then activated through the normal happy-path.
    Real ``activation``/``integration``/``closure`` blocks survive the
    repair untouched and continue to surface as blocked errors.
    """

    def test_coordination_only_blocked_row_is_repaired_and_activated(
        self, conn, stub_resolver,
    ):
        actor = seed_human_actor(conn)
        upstream_item = _seed_item(conn, item_id=9101)
        downstream_item = _seed_item(conn, item_id=9102)
        target_id = _seed_target(conn)
        upstream_claim = _seed_active_claim(
            conn, item_id=upstream_item, actor_id=actor, target_id=target_id,
        )
        downstream_claim = _seed_blocked_claim(
            conn, item_id=downstream_item, actor_id=actor,
            target_id=target_id,
            blocked_reason=f"serial-via-dependency on path_claims.id={upstream_claim}",
        )
        _add_edge(
            conn, dependent=downstream_item, blocking=upstream_item,
            gate_point="coordination_only",
        )
        result = run_activation_phase(
            conn, item_id=downstream_item, actor_id=actor,
        )
        # No block error survives; the claim ends up ``active``.
        assert result.is_blocked is False
        state = conn.execute(
            "SELECT state FROM path_claims WHERE id = %s",
            (downstream_claim,),
        ).fetchone()[0]
        assert state == "active"

    def test_real_activation_edge_block_survives_repair(
        self, conn, stub_resolver,
    ):
        actor = seed_human_actor(conn)
        upstream_item = _seed_item(conn, item_id=9201)
        downstream_item = _seed_item(conn, item_id=9202)
        target_id = _seed_target(conn)
        upstream_claim = _seed_active_claim(
            conn, item_id=upstream_item, actor_id=actor, target_id=target_id,
        )
        downstream_claim = _seed_blocked_claim(
            conn, item_id=downstream_item, actor_id=actor,
            target_id=target_id,
            blocked_reason=f"serial-via-dependency on path_claims.id={upstream_claim}",
        )
        # Real activation edge — coord-only repair must NOT touch this row.
        _add_edge(
            conn, dependent=downstream_item, blocking=upstream_item,
            gate_point="activation",
        )
        result = run_activation_phase(
            conn, item_id=downstream_item, actor_id=actor,
        )
        assert result.is_blocked is True
        state = conn.execute(
            "SELECT state FROM path_claims WHERE id = %s",
            (downstream_claim,),
        ).fetchone()[0]
        assert state == "blocked"

    def test_repair_helper_handles_six_coord_only_blocked_cluster(self, conn):
        # AC-14 shape: six downstream items each blocked behind one upstream
        # via coordination_only edges. Each downstream owns its own path
        # target (matching the live cluster, where each downstream touches
        # a different declared file). A single sweep repairs all six; an
        # additional row wired with a real ``activation`` edge stays blocked.
        from yoke_core.domain.path_claims_blocked_coordination_repair import (
            repair_coordination_only_blocked,
        )
        actor = seed_human_actor(conn)
        upstream_target = _seed_target(conn, "runtime/api/domain/upstream")
        upstream_item = _seed_item(conn, item_id=9300)
        upstream_claim = _seed_active_claim(
            conn, item_id=upstream_item, actor_id=actor,
            target_id=upstream_target,
        )
        repaired_expected: list[int] = []
        for offset in range(1, 7):
            downstream_target = _seed_target(
                conn, f"runtime/api/domain/coord_target_{offset}"
            )
            downstream_item = _seed_item(conn, item_id=9300 + offset)
            cid = _seed_blocked_claim(
                conn, item_id=downstream_item, actor_id=actor,
                target_id=downstream_target,
                blocked_reason=(
                    f"serial-via-dependency on path_claims.id={upstream_claim}"
                ),
            )
            # Coord-only edges typically arise from shared targets in real
            # usage; for the repair pass what matters is the dep edge, not
            # the target overlap. Without target overlap the repair flips
            # the row to planned (NONE classification == no live overlap).
            _add_edge(
                conn, dependent=downstream_item, blocking=upstream_item,
                gate_point="coordination_only",
            )
            repaired_expected.append(cid)
        # One additional downstream wired with a real activation edge AND
        # a shared target with the upstream — this is a legitimate block
        # that must survive repair.
        activation_target = upstream_target  # share with upstream
        activation_downstream = _seed_item(conn, item_id=9399)
        survives_blocked = _seed_blocked_claim(
            conn, item_id=activation_downstream, actor_id=actor,
            target_id=activation_target,
            blocked_reason=(
                f"serial-via-dependency on path_claims.id={upstream_claim}"
            ),
        )
        _add_edge(
            conn, dependent=activation_downstream, blocking=upstream_item,
            gate_point="activation",
        )

        repaired = repair_coordination_only_blocked(conn)
        assert sorted(repaired) == sorted(repaired_expected)
        for cid in repaired_expected:
            row = conn.execute(
                "SELECT state, blocked_reason FROM path_claims WHERE id = %s",
                (cid,),
            ).fetchone()
            assert str(row[0]) == "planned"
            assert row[1] is None
        survivor = conn.execute(
            "SELECT state, blocked_reason FROM path_claims WHERE id = %s",
            (survives_blocked,),
        ).fetchone()
        assert str(survivor[0]) == "blocked"
        assert survivor[1] is not None
