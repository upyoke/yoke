"""Tests for HC-path-claim-coordination-rationale.

Pins:

* AC-3: PASS against a clean DB.
* AC-4: FAIL when a coordination_only ``item_dependencies`` row carries
  empty rationale.
* AC-5: FAIL when a blocked ``path_claims`` row's ``blocked_reason``
  names a released upstream while another non-terminal overlap on the
  same target survives.
* AC-13: ``test_hc_ignores_exception_mode_claims`` pins that
  ``mode='exception'`` rows are sanctioned operator-override and
  silently skipped even when they otherwise match failure-mode 1.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures import pg_testdb
from runtime.api.fixtures.schema_ddl import apply_fixture_ddl
from yoke_core.engines.doctor_hc_path_claim_coordination import (
    hc_path_claim_coordination_rationale,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_DDL = """
CREATE TABLE path_claims (
    id INTEGER PRIMARY KEY, state TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'exclusive', item_id INTEGER,
    integration_target TEXT NOT NULL, blocked_reason TEXT
);
CREATE TABLE path_claim_targets (
    id INTEGER PRIMARY KEY, claim_id INTEGER NOT NULL,
    target_id INTEGER NOT NULL
);
CREATE TABLE path_targets (
    id INTEGER PRIMARY KEY, project_id TEXT NOT NULL DEFAULT 'yoke',
    kind TEXT NOT NULL DEFAULT 'file', path_string TEXT NOT NULL,
    parent_target_id INTEGER
);
CREATE TABLE item_dependencies (
    id INTEGER PRIMARY KEY, dependent_item TEXT NOT NULL,
    blocking_item TEXT NOT NULL,
    gate_point TEXT NOT NULL DEFAULT 'activation', rationale TEXT
);
"""


@pytest.fixture
def conn():
    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    apply_fixture_ddl(c, _DDL)
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


def _seed_claim(
    conn, *, claim_id: int, state: str, target_id: int,
    mode: str = "exclusive", blocked_reason: str | None = None,
) -> None:
    conn.execute(
        "INSERT INTO path_claims (id, state, mode, item_id, "
        "integration_target, blocked_reason) VALUES (%s, %s, %s, %s, 'main', %s)",
        (claim_id, state, mode, claim_id + 8000, blocked_reason),
    )
    conn.execute(
        "INSERT INTO path_claim_targets (claim_id, target_id) VALUES (%s, %s)",
        (claim_id, target_id),
    )
    conn.commit()


def _seed_target(
    conn, *, target_id: int, path: str, parent_target_id: int | None = None,
) -> None:
    conn.execute(
        "INSERT INTO path_targets "
        "(id, project_id, kind, path_string, parent_target_id) "
        "VALUES (%s, 'yoke', 'file', %s, %s)",
        (target_id, path, parent_target_id),
    )
    conn.commit()


def _seed_coord_edge(
    conn, *, dependent: int, blocking: int, rationale: str | None,
) -> None:
    conn.execute(
        "INSERT INTO item_dependencies (dependent_item, blocking_item, "
        "gate_point, rationale) VALUES (%s, %s, 'coordination_only', %s)",
        (f"YOK-{dependent}", f"YOK-{blocking}", rationale),
    )
    conn.commit()


def _run_hc(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_path_claim_coordination_rationale(conn, DoctorArgs(), rec)
    return rec


def test_pass_when_no_rows(conn):
    assert _run_hc(conn).results[0].result == "PASS"


def test_fail_when_coordination_edge_has_empty_rationale(conn):
    _seed_coord_edge(conn, dependent=7001, blocking=7002, rationale="")
    result = _run_hc(conn).results[0]
    assert result.result == "WARN"
    assert "coordination_only" in result.detail
    assert "empty rationale" in result.detail


def test_fail_when_coordination_edge_has_null_rationale(conn):
    _seed_coord_edge(conn, dependent=7101, blocking=7102, rationale=None)
    assert "empty rationale" in _run_hc(conn).results[0].detail


def test_pass_when_coordination_edge_has_authored_rationale(conn):
    _seed_coord_edge(
        conn, dependent=7201, blocking=7202,
        rationale="Both edits to runtime/api/foo are independent.",
    )
    assert _run_hc(conn).results[0].result == "PASS"


def test_fail_when_blocked_reason_names_released_with_surviving_overlap(
    conn,
):
    target, upstream, survivor, blocked_id = 9999, 101, 102, 103
    _seed_claim(conn, claim_id=upstream, state="released", target_id=target)
    _seed_claim(conn, claim_id=survivor, state="active", target_id=target)
    _seed_claim(
        conn, claim_id=blocked_id, state="blocked", target_id=target,
        blocked_reason=f"path_claims.id={upstream}",
    )
    result = _run_hc(conn).results[0]
    assert result.result == "WARN"
    assert f"path_claims.id={blocked_id}" in result.detail
    assert f"path_claims.id={upstream}" in result.detail


def test_fail_for_lineage_overlap_after_released_upstream(conn):
    parent, child = 9100, 9101
    upstream, survivor, blocked_id = 501, 502, 503
    _seed_target(conn, target_id=parent, path="docs")
    _seed_target(conn, target_id=child, path="docs/lifecycle.md", parent_target_id=parent)
    _seed_claim(conn, claim_id=upstream, state="released", target_id=child)
    _seed_claim(conn, claim_id=survivor, state="active", target_id=parent)
    _seed_claim(
        conn, claim_id=blocked_id, state="blocked", target_id=child,
        blocked_reason=f"path_claims.id={upstream}",
    )

    result = _run_hc(conn).results[0]
    assert result.result == "WARN"
    assert f"path_claims.id={blocked_id}" in result.detail


def test_pass_when_blocked_reason_names_released_without_survivor(conn):
    # No survivor on the same target — propagation will flip the
    # blocked row to planned; the HC must not flag.
    target, upstream, blocked_id = 9998, 201, 202
    _seed_claim(conn, claim_id=upstream, state="released", target_id=target)
    _seed_claim(
        conn, claim_id=blocked_id, state="blocked", target_id=target,
        blocked_reason=f"path_claims.id={upstream}",
    )
    assert _run_hc(conn).results[0].result == "PASS"


def test_pass_when_blocked_reason_names_active_upstream(conn):
    # Upstream still active — no staleness.
    target, upstream, blocked_id = 9997, 301, 302
    _seed_claim(conn, claim_id=upstream, state="active", target_id=target)
    _seed_claim(
        conn, claim_id=blocked_id, state="blocked", target_id=target,
        blocked_reason=f"path_claims.id={upstream}",
    )
    assert _run_hc(conn).results[0].result == "PASS"


def test_hc_ignores_exception_mode_claims(conn):
    """AC-13: ``mode='exception'`` is sanctioned operator-override and
    must NOT be flagged even when matching failure-mode 1.

    Seed two rows that BOTH match the stale-blocked_reason pattern:
    one ``mode='exclusive'`` (must FAIL), one ``mode='exception'``
    (must be silently skipped).
    """
    target, upstream, survivor, std, exc = 9996, 401, 402, 403, 404
    _seed_claim(conn, claim_id=upstream, state="released", target_id=target)
    _seed_claim(conn, claim_id=survivor, state="active", target_id=target)
    _seed_claim(
        conn, claim_id=std, state="blocked", target_id=target,
        blocked_reason=f"path_claims.id={upstream}", mode="exclusive",
    )
    _seed_claim(
        conn, claim_id=exc, state="blocked", target_id=target,
        blocked_reason=f"path_claims.id={upstream}", mode="exception",
    )
    result = _run_hc(conn).results[0]
    assert result.result == "WARN"
    assert f"path_claims.id={std}" in result.detail
    assert f"path_claims.id={exc}" not in result.detail


def test_pass_when_path_claims_table_missing(conn):
    conn.execute("DROP TABLE path_claims")
    conn.commit()
    assert _run_hc(conn).results[0].result == "PASS"


def test_handles_item_dependencies_missing(conn):
    conn.execute("DROP TABLE item_dependencies")
    conn.commit()
    assert _run_hc(conn).results[0].result == "PASS"
