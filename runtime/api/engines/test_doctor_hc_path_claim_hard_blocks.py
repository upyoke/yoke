"""Integration tests for the path-claim hard-block Doctor HC.

Verifies that the HC self-skips cleanly on minimal-schema fixtures,
PASSes when no over-hard rows exist, and WARNs with the expected
remediation prose when an over-hard activation edge is present.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import pytest

from yoke_core.domain.project_seed_test_helpers import seed_project_identities

from yoke_core.domain import schema, shepherd_init
from yoke_core.engines.doctor_hc_path_claim_hard_blocks import (
    hc_path_claim_hard_blocks,
)
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


def _apply_canonical_schema() -> None:
    """``apply_schema`` strategy: full canonical schema + shepherd tables.

    Both ``schema.cmd_init`` and ``shepherd_init.cmd_init`` resolve their
    connection through the backend factory, so the tables co-locate on the
    active backend (SQLite file or the repointed Postgres test database).
    """
    from yoke_core.domain import db_backend

    schema.cmd_init()
    conn = db_backend.connect()
    try:
        seed_project_identities(conn)
        shepherd_init.cmd_init(conn)
    finally:
        conn.close()


def _insert_item(conn, *, item_id: int, title: str, status: str) -> None:
    conn.execute(
        "INSERT INTO items "
        "(id, title, type, status, priority, project_id, project_sequence, "
        "created_at, updated_at) "
        "VALUES (%s, %s, 'issue', %s, 'medium', 1, %s, "
        "'2026-05-13T00:00:00Z', '2026-05-13T00:00:00Z')",
        (item_id, title, status, item_id),
    )
    conn.commit()


def _insert_dependency(
    conn, *, dependent: str, blocking: str, source: str = "idea",
    rationale: str = "", gate_point: str = "activation",
) -> int:
    cur = conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item, blocking_item, gate_point, satisfaction, source, "
        "rationale, evidence_json, created_at) "
        "VALUES (%s, %s, %s, 'status:done', %s, %s, '{}', "
        "'2026-05-13T00:00:00Z') RETURNING id",
        (dependent, blocking, gate_point, source, rationale),
    )
    dep_id = int(cur.fetchone()[0])
    conn.commit()
    return dep_id


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict]:
    with init_test_db(tmp_path, apply_schema=_apply_canonical_schema) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        conn = connect_test_db(db_path)
        try:
            yield {"db_path": db_path, "conn": conn}
        finally:
            conn.close()


def test_hc_pass_when_no_over_hard_rows(env):
    rec = RecordCollector()
    hc_path_claim_hard_blocks(env["conn"], DoctorArgs(), rec)
    assert len(rec.results) == 1
    result = rec.results[0]
    assert result.check_id == "HC-path-claim-hard-blocks"
    assert result.result == "PASS"


def _apply_empty_schema() -> None:
    """``apply_schema`` strategy that creates no tables.

    The HC's ``_table_exists`` read resolves through backend-native schema
    helpers, so an actually empty test database exercises the minimal-schema
    skip branch on both engines.
    """


def test_hc_self_skip_on_minimal_schema(tmp_path: Path):
    with init_test_db(tmp_path, apply_schema=_apply_empty_schema) as db_path:
        conn = connect_test_db(db_path)
        try:
            rec = RecordCollector()
            hc_path_claim_hard_blocks(conn, DoctorArgs(), rec)
            assert len(rec.results) == 1
            assert rec.results[0].result == "PASS"
            assert "skipping" in rec.results[0].detail
        finally:
            conn.close()


def test_hc_warns_on_over_hard_activation_edge(env):
    conn = env["conn"]
    _insert_item(conn, item_id=666, title="candidate", status="refined-idea")
    _insert_item(conn, item_id=665, title="upstream", status="implementing")
    _insert_dependency(
        conn,
        dependent="YOK-666",
        blocking="YOK-665",
        rationale=(
            "Path-claim overlap with YOK-665 on "
            ".agents/skills/yoke/shepherd/design-checks.md"
        ),
        source="idea",
    )

    rec = RecordCollector()
    hc_path_claim_hard_blocks(conn, DoctorArgs(), rec)
    assert len(rec.results) == 1
    result = rec.results[0]
    assert result.result == "WARN"
    assert "YOK-666" in result.detail
    assert "YOK-665" in result.detail
    assert "coordination_only" in result.detail
    assert "decision=directional" in result.detail


def test_hc_skips_directional_rows(env):
    conn = env["conn"]
    _insert_item(conn, item_id=672, title="candidate", status="refined-idea")
    _insert_item(conn, item_id=665, title="upstream", status="implementing")
    _insert_dependency(
        conn,
        dependent="YOK-672",
        blocking="YOK-665",
        rationale=(
            "decision=directional. shared_paths=docs/hook-parity-map.md. "
            "why_order_matters=table reordering"
        ),
        source="idea",
    )

    rec = RecordCollector()
    hc_path_claim_hard_blocks(conn, DoctorArgs(), rec)
    assert len(rec.results) == 1
    assert rec.results[0].result == "PASS"
