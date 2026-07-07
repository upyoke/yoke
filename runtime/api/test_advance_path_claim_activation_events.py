"""Event-emission coverage for the advance path-claim activation phase.

Pairs with :mod:`yoke_core.domain.advance_path_claim_activation_events`.
The activation phase's blocked branch must emit a single
``PathClaimActivationBlocked`` event per blocked claim per phase
invocation, deduped by ``(session_id, claim_id, item_id)``. The legacy
``test_advance_path_claim_activation.py`` covers state-mutation
branching; this sibling owns the event-shape and idempotency
assertions so the legacy file stays under the per-file line cap.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain import advance_path_claim_activation as _module
from yoke_core.domain import db_backend
from yoke_core.domain.actors import seed_canonical_actors, seed_human_actor  # noqa: F401
from yoke_core.domain.advance_path_claim_activation import (
    run_activation_phase,
)
from yoke_core.domain.events_schema import _create_events_table
from yoke_core.domain.schema_init_actor_path_claim_tables import (
    create_actor_path_claim_tables,
)
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
    _create_events_table(c)
    seed_canonical_actors(c)
    c.execute(
        "INSERT INTO projects "
        "(id, slug, name, public_item_prefix, created_at) "
        "VALUES (1, 'yoke', 'yoke', 'YOK', "
        "'2026-05-01T00:00:00Z') "
        "ON CONFLICT(id) DO NOTHING"
    )
    c.execute(
        "INSERT INTO path_snapshots (project_id, commit_sha, built_at) "
        "VALUES (1, 'snap-base', '2026-05-01T00:00:00Z')"
    )
    c.commit()
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


@pytest.fixture
def stub_resolver(monkeypatch):
    def _stub(conn, *, project_id, repo_path, integration_target):
        return "snap-base"

    from yoke_core.domain import advance_path_claim_activation_retry as _retry
    monkeypatch.setattr(
        _retry,
        "resolve_integration_head_with_divergence_check",
        _stub,
    )


def _seed_blocked(conn, *, blocked_reason: str) -> tuple[int, int]:
    actor = seed_human_actor(conn)
    item_id = 9001
    overlap_item_id = 8901
    for iid, title in ((item_id, "downstream"), (overlap_item_id, "overlap")):
        conn.execute(
            "INSERT INTO items (id, title, type, status, priority, "
            "created_at, updated_at, project_id, project_sequence) "
            "VALUES (%s, %s, 'issue', 'idea', 'medium', "
            "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
            (iid, title, iid),
        )
    cur = conn.execute(
        "INSERT INTO path_targets "
        "(project_id, kind, path_string, generation, created_at) "
        "VALUES (1, 'directory', 'runtime/api/domain', 1, "
        "'2026-05-01T00:00:00Z') RETURNING id"
    )
    target_id = int(cur.fetchone()[0])
    # Active overlap-only sibling with NO ``item_dependencies`` edge so
    # the advance-time repair pass classifies the blocked row as
    # ``INCOMPATIBLE`` (real overlap, no dep edge). The blocked row
    # survives the repair, and the activation phase's blocked branch
    # emits the expected event.
    cur = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, actor_id, item_id, integration_target, "
        "registered_at, activated_at, base_commit_sha) "
        "VALUES ('active', 'exclusive', %s, %s, 'main', "
        "'2026-05-01T00:00:00Z', '2026-05-01T01:00:00Z', 'snap-base') "
        "RETURNING id",
        (actor, overlap_item_id),
    )
    overlap_claim_id = int(cur.fetchone()[0])
    conn.execute(
        "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
        "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
        (overlap_claim_id, target_id),
    )
    cur = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, actor_id, item_id, integration_target, "
        " registered_at, blocked_reason) "
        "VALUES ('blocked', 'exclusive', %s, %s, 'main', "
        "'2026-05-01T00:00:00Z', %s) RETURNING id",
        (actor, item_id, blocked_reason),
    )
    claim_id = int(cur.fetchone()[0])
    conn.execute(
        "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
        "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
        (claim_id, target_id),
    )
    conn.commit()
    return claim_id, actor


class TestBlockedBranchEmitsEvent:
    def test_blocked_branch_emits_event_with_envelope_shape(
        self, conn, stub_resolver,
    ):
        claim_id, actor = _seed_blocked(
            conn, blocked_reason="serial-via-dependency on path_claims.id=42",
        )
        run_activation_phase(
            conn, item_id=9001, actor_id=actor,
            session_id="test-session",
        )
        rows = conn.execute(
            "SELECT event_name, envelope, session_id, item_id "
            "FROM events WHERE event_name = 'PathClaimActivationBlocked'",
        ).fetchall()
        assert len(rows) == 1
        envelope = json.loads(rows[0]["envelope"])
        ctx = envelope["context"]
        assert ctx["claim_id"] == claim_id
        assert ctx["blocking_claim_id"] == 42
        assert "path_claims.id=42" in ctx["reason"]
        assert ctx["integration_target"] == "main"
        assert rows[0]["session_id"] == "test-session"
        assert str(rows[0]["item_id"]) == "9001"

    def test_blocked_branch_event_is_idempotent_per_invocation(
        self, conn, stub_resolver,
    ):
        _, actor = _seed_blocked(
            conn, blocked_reason="serial-via-dependency on path_claims.id=42",
        )
        # A single phase invocation must emit exactly one event per
        # blocked claim, even when iteration could revisit the row.
        run_activation_phase(
            conn, item_id=9001, actor_id=actor,
            session_id="test-session",
        )
        count = conn.execute(
            "SELECT COUNT(*) FROM events "
            "WHERE event_name = 'PathClaimActivationBlocked' "
            "AND session_id = 'test-session'",
        ).fetchone()[0]
        assert count == 1

    def test_blocked_reason_without_upstream_marker(
        self, conn, stub_resolver,
    ):
        # When blocked_reason has no canonical ``path_claims.id=N`` marker,
        # blocking_claim_id is None and the verbatim reason still ships.
        _, actor = _seed_blocked(
            conn, blocked_reason="upstream lease held by ops",
        )
        run_activation_phase(
            conn, item_id=9001, actor_id=actor,
            session_id="test-session",
        )
        rows = conn.execute(
            "SELECT envelope FROM events "
            "WHERE event_name = 'PathClaimActivationBlocked'",
        ).fetchall()
        assert len(rows) == 1
        ctx = json.loads(rows[0]["envelope"])["context"]
        assert ctx["blocking_claim_id"] is None
        assert ctx["reason"] == "upstream lease held by ops"
