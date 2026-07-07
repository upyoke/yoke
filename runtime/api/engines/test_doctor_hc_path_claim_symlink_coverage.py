"""Tests for HC-path-claim-symlink-coverage.

Three fixture corruptions against synced symlink facts:

* a — Claim covers symlink-name only. Flagged.
* b — Claim covers canonical-name only, a sibling claim covers
  symlink-name only. Sibling flagged.
* c — Claim covers BOTH names. Not flagged.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.fixtures import pg_testdb
from yoke_core.domain.path_claims_symlink_expansion import (
    SYMLINK_CANONICALIZED,
)
from yoke_core.engines.doctor_hc_path_claim_symlink_coverage import (
    hc_path_claim_symlink_coverage,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_MIN_SCHEMA_DDL = """
CREATE TABLE projects (
    id INTEGER PRIMARY KEY, slug TEXT UNIQUE);
CREATE TABLE items (
    id INTEGER PRIMARY KEY, project_id INTEGER DEFAULT 1);
CREATE TABLE path_targets (
    id INTEGER PRIMARY KEY, project_id INTEGER, path_string TEXT);
CREATE TABLE path_claims (
    id INTEGER PRIMARY KEY, item_id INTEGER, state TEXT,
    mode TEXT, integration_target TEXT);
CREATE TABLE path_claim_targets (
    claim_id INTEGER, target_id INTEGER,
    PRIMARY KEY (claim_id, target_id));
CREATE TABLE path_snapshots (
    id INTEGER PRIMARY KEY, project_id INTEGER, commit_sha TEXT,
    built_at TEXT);
CREATE TABLE path_snapshot_symlink_facts (
    snapshot_id INTEGER, symlink_path TEXT, reason TEXT,
    target_attempt TEXT, canonical_path TEXT);
"""


@pytest.fixture
def conn() -> Any:
    from runtime.api.fixtures.schema_ddl import apply_fixture_ddl

    name = pg_testdb.create_test_database()
    c = pg_testdb.connect_test_database(name)
    apply_fixture_ddl(c, _MIN_SCHEMA_DDL)
    c.execute(
        "INSERT INTO projects (id, slug) VALUES (%s, %s)",
        (1, "yoke"),
    )
    c.execute("INSERT INTO items (id, project_id) VALUES (1, 1)")
    c.execute("INSERT INTO items (id, project_id) VALUES (2, 1)")
    # path_targets seeds for AGENTS.md (251) and CLAUDE.md (252)
    c.execute(
        "INSERT INTO path_targets (id, project_id, path_string) "
        "VALUES (251, 1, 'AGENTS.md')"
    )
    c.execute(
        "INSERT INTO path_targets (id, project_id, path_string) "
        "VALUES (252, 1, 'CLAUDE.md')"
    )
    _seed_symlink_fact(c)
    yield c
    c.close()
    pg_testdb.drop_test_database(name)


def _seed_symlink_fact(conn: Any) -> None:
    row = conn.execute(
        "INSERT INTO path_snapshots (project_id, commit_sha, built_at) "
        "VALUES (1, 'sha-symlink', '2026-05-11T00:00:00Z') RETURNING id",
    ).fetchone()
    conn.execute(
        "INSERT INTO path_snapshot_symlink_facts "
        "(snapshot_id, symlink_path, reason, target_attempt, canonical_path) "
        "VALUES (%s, 'CLAUDE.md', %s, 'AGENTS.md', 'AGENTS.md')",
        (int(row[0]), SYMLINK_CANONICALIZED),
    )


def _seed_claim(
    conn: Any, *,
    claim_id: int, item_id: int, target_ids: list[int],
) -> None:
    conn.execute(
        "INSERT INTO path_claims (id, item_id, state, mode, integration_target) "
        "VALUES (%s, %s, 'active', 'exclusive', 'main')",
        (claim_id, item_id),
    )
    for tid in target_ids:
        conn.execute(
            "INSERT INTO path_claim_targets (claim_id, target_id) VALUES (%s, %s)",
            (claim_id, tid),
        )


def _run(conn) -> RecordCollector:
    rec = RecordCollector()
    hc_path_claim_symlink_coverage(conn, DoctorArgs(), rec)
    return rec


class TestSymlinkCoverageHC:
    def test_a_symlink_only_is_flagged(self, conn):
        _seed_claim(conn, claim_id=1, item_id=1, target_ids=[252])
        rec = _run(conn)
        assert rec.results[0].result == "WARN"
        assert "CLAUDE.md" in rec.results[0].detail
        assert "AGENTS.md" in rec.results[0].detail

    def test_b_sibling_symlink_only_is_flagged_not_canonical_claim(self, conn):
        # Claim 1 covers canonical only (AGENTS.md) — not flagged on this row.
        _seed_claim(conn, claim_id=1, item_id=1, target_ids=[251])
        # Sibling claim 2 covers symlink only — this is the offender.
        _seed_claim(conn, claim_id=2, item_id=2, target_ids=[252])
        rec = _run(conn)
        assert rec.results[0].result == "WARN"
        detail = rec.results[0].detail
        assert "path_claims.id=2" in detail
        assert "path_claims.id=1" not in detail

    def test_c_both_names_covered_not_flagged(self, conn):
        _seed_claim(conn, claim_id=1, item_id=1, target_ids=[251, 252])
        rec = _run(conn)
        assert rec.results[0].result == "PASS"

    def test_exception_mode_claim_is_skipped(self, conn):
        _seed_claim(conn, claim_id=1, item_id=1, target_ids=[252])
        conn.execute(
            "UPDATE path_claims SET mode='exception' WHERE id=1"
        )
        rec = _run(conn)
        assert rec.results[0].result == "PASS"

    def test_checkout_mapping_not_required(self, conn):
        _seed_claim(conn, claim_id=1, item_id=1, target_ids=[252])
        rec = _run(conn)
        assert rec.results[0].result == "WARN"
        assert "CLAUDE.md" in rec.results[0].detail
