"""Dep-graph regression coverage for ``register_for_item``.

The bug this file regresses: ``register_for_item`` historically dropped
``candidate_item_id`` before calling :func:`path_claims.register`, so
the overlap classifier could not invoke its
``has_bidirectional_dep_edge`` branch on the candidate side. The fix
threads ``candidate_item_id`` through and lets ``register_for_item``
auto-resolve the upstream id via ``auto_resolve_upstream`` so the
resulting blocked row carries the upstream-naming ``blocked_reason``.

Test shapes:

* (a) No dep-edges, no ``--upstream-claim-id`` → ``IncompatibleOverlap``.
* (b) Single dep-edge, no ``--upstream-claim-id`` → claim registers in
  ``state='blocked'`` with ``blocked_reason`` naming the upstream id.
* (c) Multi-overlap candidate (the reproduction shape — three
  upstream items, three overlapping claims, dep-edges to all) →
  registration succeeds with ``state='blocked'``.
* (d) Explicit ``--upstream-claim-id`` matching one overlapping claim,
  no dep-edges → ``state='blocked'`` (regression of pre-fix behavior).

AC-5 reproduces the filing shape end-to-end and asserts
post-fix success.
"""

from __future__ import annotations


import pytest

from yoke_core.domain._path_claims_test_helpers import (  # noqa: F401
    SNAP,
    conn,
    local_human,
    seed_target,
)
from yoke_core.domain.path_claims import (
    IncompatibleOverlap,
    get_claim,
)
from yoke_core.domain.path_claims_register import register_for_item


# ---------------------------------------------------------------------------
# Seeding helpers
# ---------------------------------------------------------------------------


def _seed_item(conn, item_id: int) -> int:
    conn.execute(
        "INSERT INTO items (id, title, type, status, priority, "
        "created_at, updated_at, project_id, project_sequence) "
        "VALUES (%s, 'item', 'issue', 'idea', 'medium', "
        "'2026-05-01T00:00:00Z', '2026-05-01T00:00:00Z', 1, %s)",
        (item_id, item_id),
    )
    conn.commit()
    return item_id


def _ensure_item_dependencies_table(conn) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS item_dependencies ("
        "id INTEGER PRIMARY KEY, dependent_item TEXT NOT NULL, "
        "blocking_item TEXT NOT NULL, "
        "gate_point TEXT NOT NULL DEFAULT 'activation', "
        "satisfaction TEXT NOT NULL DEFAULT 'status:done', "
        "source TEXT NOT NULL, session_id INTEGER, "
        "rationale TEXT NOT NULL DEFAULT '', "
        "evidence_json TEXT NOT NULL DEFAULT '{}', "
        "created_at TEXT NOT NULL)"
    )
    conn.commit()


def _add_dep_edge(
    conn, *, dependent: int, blocking: int,
) -> None:
    _ensure_item_dependencies_table(conn)
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item, blocking_item, source, created_at) "
        "VALUES (%s, %s, 'test', '2026-05-01T00:00:00Z')",
        (f"YOK-{dependent}", f"YOK-{blocking}"),
    )
    conn.commit()


def _seed_active_claim_for_path(
    conn,
    *,
    item_id: int,
    path_string: str,
) -> tuple[int, int]:
    """Seed a path_targets row + active path_claim covering it.

    Returns ``(claim_id, target_id)``.
    """
    cur = conn.execute(
        "INSERT INTO path_targets "
        "(project_id, kind, path_string, generation, created_at) "
        "VALUES (1, 'file', %s, 1, '2026-05-01T00:00:00Z') "
        "RETURNING id",
        (path_string,),
    )
    target_id = int(cur.fetchone()[0])
    actor = local_human(conn)
    cur = conn.execute(
        "INSERT INTO path_claims "
        "(state, mode, actor_id, item_id, integration_target, "
        "registered_at, activated_at, base_commit_sha) "
        "VALUES ('active', 'exclusive', %s, %s, 'main', "
        "'2026-05-01T00:00:00Z', '2026-05-01T01:00:00Z', %s) "
        "RETURNING id",
        (actor, item_id, SNAP),
    )
    claim_id = int(cur.fetchone()[0])
    conn.execute(
        "INSERT INTO path_claim_targets (claim_id, target_id, declared_at) "
        "VALUES (%s, %s, '2026-05-01T00:00:00Z')",
        (claim_id, target_id),
    )
    conn.commit()
    return claim_id, target_id


# ---------------------------------------------------------------------------
# AC-4 coverage
# ---------------------------------------------------------------------------


class TestNoDepEdgeStillIncompatible:
    """AC-4(a): pre-fix behavior must remain a regression target."""

    def test_no_edges_no_upstream_rejects(self, conn):
        upstream = _seed_item(conn, item_id=51001)
        candidate = _seed_item(conn, item_id=51002)
        _ensure_item_dependencies_table(conn)
        _seed_active_claim_for_path(
            conn, item_id=upstream,
            path_string="runtime/api/domain/no_edge_target.py",
        )

        with pytest.raises(IncompatibleOverlap):
            register_for_item(
                conn,
                item_id=candidate,
                integration_target="main",
                paths=["runtime/api/domain/no_edge_target.py"],
                actor_id=local_human(conn),
                allow_planned=True,
            )


class TestSingleDepEdgeAutoResolves:
    """AC-4(b): one dep-edge → blocked claim names the upstream id."""

    def test_single_edge_lands_blocked_with_upstream_id(self, conn):
        upstream = _seed_item(conn, item_id=51011)
        candidate = _seed_item(conn, item_id=51012)
        upstream_claim, _ = _seed_active_claim_for_path(
            conn, item_id=upstream,
            path_string="runtime/api/domain/single_edge_target.py",
        )
        _add_dep_edge(conn, dependent=candidate, blocking=upstream)

        claim_id = register_for_item(
            conn,
            item_id=candidate,
            integration_target="main",
            paths=["runtime/api/domain/single_edge_target.py"],
            actor_id=local_human(conn),
            allow_planned=True,
        )
        claim = get_claim(conn, claim_id)
        assert claim["state"] == "blocked"
        assert claim["blocked_reason"] == (
            f"serial-via-dependency on path_claims.id={upstream_claim}"
        )


class TestMultiOverlapAllEdges:
    """AC-4(c): multi-overlap candidate lands blocked."""

    def test_multi_overlap_with_partial_dep_edges_still_rejects(self, conn):
        u1 = _seed_item(conn, item_id=51041)
        u2 = _seed_item(conn, item_id=51042)
        candidate = _seed_item(conn, item_id=51043)
        for upstream, path in [
            (u1, "runtime/api/domain/partial_path_a.py"),
            (u2, "runtime/api/domain/partial_path_b.py"),
        ]:
            _seed_active_claim_for_path(
                conn, item_id=upstream, path_string=path,
            )
        _add_dep_edge(conn, dependent=candidate, blocking=u1)

        with pytest.raises(IncompatibleOverlap):
            register_for_item(
                conn,
                item_id=candidate,
                integration_target="main",
                paths=[
                    "runtime/api/domain/partial_path_a.py",
                    "runtime/api/domain/partial_path_b.py",
                ],
                actor_id=local_human(conn),
                allow_planned=True,
            )

    def test_multi_overlap_with_all_dep_edges_lands_blocked(self, conn):
        u1 = _seed_item(conn, item_id=51021)
        u2 = _seed_item(conn, item_id=51022)
        u3 = _seed_item(conn, item_id=51023)
        candidate = _seed_item(conn, item_id=51024)
        upstream_claims = []
        for upstream, path in [
            (u1, "runtime/api/domain/multi_path_a.py"),
            (u2, "runtime/api/domain/multi_path_b.py"),
            (u3, "runtime/api/domain/multi_path_c.py"),
        ]:
            cid, _ = _seed_active_claim_for_path(
                conn, item_id=upstream, path_string=path,
            )
            upstream_claims.append(cid)
            _add_dep_edge(conn, dependent=candidate, blocking=upstream)

        claim_id = register_for_item(
            conn,
            item_id=candidate,
            integration_target="main",
            paths=[
                "runtime/api/domain/multi_path_a.py",
                "runtime/api/domain/multi_path_b.py",
                "runtime/api/domain/multi_path_c.py",
            ],
            actor_id=local_human(conn),
            allow_planned=True,
        )
        claim = get_claim(conn, claim_id)
        assert claim["state"] == "blocked"
        # The auto-resolver returns one of the overlapping upstreams; the
        # exact id depends on row ordering, but it MUST be one of them.
        marker = "serial-via-dependency on path_claims.id="
        assert (claim["blocked_reason"] or "").startswith(marker)
        named = int((claim["blocked_reason"] or "").rsplit("=", 1)[-1])
        assert named in upstream_claims


class TestExplicitUpstreamWithoutDepEdge:
    """AC-4(d): explicit ``--upstream-claim-id`` regression."""

    def test_explicit_upstream_alone_lands_blocked(self, conn):
        upstream = _seed_item(conn, item_id=51031)
        candidate = _seed_item(conn, item_id=51032)
        _ensure_item_dependencies_table(conn)
        upstream_claim, _ = _seed_active_claim_for_path(
            conn, item_id=upstream,
            path_string="runtime/api/domain/explicit_upstream_target.py",
        )

        claim_id = register_for_item(
            conn,
            item_id=candidate,
            integration_target="main",
            paths=["runtime/api/domain/explicit_upstream_target.py"],
            upstream_claim_id=upstream_claim,
            actor_id=local_human(conn),
            allow_planned=True,
        )
        claim = get_claim(conn, claim_id)
        assert claim["state"] == "blocked"
        assert claim["blocked_reason"] == (
            f"serial-via-dependency on path_claims.id={upstream_claim}"
        )


# ---------------------------------------------------------------------------
# AC-5 coverage — reproduction shape
# ---------------------------------------------------------------------------


class TestYok1619Reproduction:
    """AC-5: the exact shape that motivated this ticket.

    Three upstream items, each holding a non-terminal path claim on a
    distinct overlapping path. Candidate has dep-edges to all three.
    Pre-fix: registration would raise ``IncompatibleOverlap``. Post-fix:
    the candidate registers in ``state='blocked'``.
    """

    def test_three_upstream_items_with_edges_register_blocked(self, conn):
        u_a = _seed_item(conn, item_id=51101)
        u_b = _seed_item(conn, item_id=51102)
        u_c = _seed_item(conn, item_id=51103)
        candidate = _seed_item(conn, item_id=51104)
        upstream_claims = []
        for upstream, path in [
            (u_a, "runtime/api/domain/populate_registry_data_authoritative.py"),
            (u_b, "runtime/harness/harness_sessions_claims_acquire.py"),
            (u_c, "AGENTS.md"),
        ]:
            cid, _ = _seed_active_claim_for_path(
                conn, item_id=upstream, path_string=path,
            )
            upstream_claims.append(cid)
            _add_dep_edge(conn, dependent=candidate, blocking=upstream)

        claim_id = register_for_item(
            conn,
            item_id=candidate,
            integration_target="main",
            paths=[
                "runtime/api/domain/populate_registry_data_authoritative.py",
                "runtime/harness/harness_sessions_claims_acquire.py",
                "AGENTS.md",
            ],
            actor_id=local_human(conn),
            allow_planned=True,
        )
        claim = get_claim(conn, claim_id)
        assert claim["state"] == "blocked"
        marker = "serial-via-dependency on path_claims.id="
        assert (claim["blocked_reason"] or "").startswith(marker)
        named = int((claim["blocked_reason"] or "").rsplit("=", 1)[-1])
        assert named in upstream_claims
