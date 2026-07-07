"""Tests for ``yoke_core.domain.shepherd_gate``.

Covers the advance preflight Shepherd Lifecycle Gate's three required states:

1. Modern verdict (``planning_to_plan_drafted``) in an acceptable state
   satisfies the gate.
2. Legacy verdict (``planned_to_ready``) in an acceptable state satisfies
   the gate for pre-2026-04-07 compatibility.
3. Absence of any qualifying verdict blocks the gate.

These scenarios are the direct Python analog of the bash query previously
embedded in ``.agents/skills/yoke/advance/preflight-checks.md``. Extracting
the query into Python lets the advance skill call a single module entrypoint
instead of duplicating SQL in prose — and lets this test pin the contract
against drift.
"""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.conftest import insert_item
from yoke_core.domain import db_backend
from yoke_core.domain import shepherd_gate
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)


@pytest.fixture
def tmp_db(tmp_path):
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as path:
        yield path


def _open(path: str):
    return connect_test_db(path)


def _insert_verdict(
    conn: Any,
    item_ref: str,
    transition: str,
    verdict: str,
    worker: str = "architect",
    created_at: str = "2026-04-21T12:00:00Z",
) -> None:
    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    conn.execute(
        "INSERT INTO shepherd_verdicts (item, transition, worker, verdict, created_at) "
        f"VALUES ({p}, {p}, {p}, {p}, {p})",
        (item_ref, transition, worker, verdict, created_at),
    )
    conn.commit()


class TestShepherdGate:
    def test_modern_verdict_passes(self, tmp_db):
        """Gate passes when the modern shepherd verdict is present."""
        conn = _open(tmp_db)
        try:
            insert_item(conn, id=501, title="Modern epic", type="epic",
                        status="planned", spec="body")
            _insert_verdict(conn, "YOK-501", "planning_to_plan_drafted", "READY")
            result = shepherd_gate.check_gate(501, conn=conn)
        finally:
            conn.close()

        assert result.passed is True
        assert result.transition == "planning_to_plan_drafted"
        assert result.verdict == "READY"

    def test_modern_verdict_caveats_passes(self, tmp_db):
        """CAVEATS on the modern verdict is still accepted."""
        conn = _open(tmp_db)
        try:
            insert_item(conn, id=502, title="Epic with caveats", type="epic",
                        status="planned", spec="body")
            _insert_verdict(conn, "YOK-502", "planning_to_plan_drafted", "CAVEATS")
            result = shepherd_gate.check_gate(502, conn=conn)
        finally:
            conn.close()

        assert result.passed is True
        assert result.verdict == "CAVEATS"

    def test_legacy_verdict_passes(self, tmp_db):
        """Legacy pre-2026-04-07 verdict still satisfies the gate."""
        conn = _open(tmp_db)
        try:
            insert_item(conn, id=503, title="Historical epic", type="epic",
                        status="done", spec="body")
            _insert_verdict(conn, "YOK-503", "planned_to_ready", "READY",
                            created_at="2026-04-03T12:00:00Z")
            result = shepherd_gate.check_gate(503, conn=conn)
        finally:
            conn.close()

        assert result.passed is True
        assert result.transition == "planned_to_ready"
        assert result.verdict == "READY"
        assert "compat" in result.reason.lower()

    def test_no_verdict_blocks(self, tmp_db):
        """Absence of any qualifying verdict blocks the gate."""
        conn = _open(tmp_db)
        try:
            insert_item(conn, id=504, title="Unsigned epic", type="epic",
                        status="planned", spec="body")
            result = shepherd_gate.check_gate(504, conn=conn)
        finally:
            conn.close()

        assert result.passed is False
        assert result.transition is None
        assert result.verdict is None
        assert "planning_to_plan_drafted" in result.reason

    def test_rejected_verdict_does_not_satisfy(self, tmp_db):
        """REJECTED or other non-accepted verdicts do not satisfy the gate."""
        conn = _open(tmp_db)
        try:
            insert_item(conn, id=505, title="Rejected plan", type="epic",
                        status="planned", spec="body")
            _insert_verdict(conn, "YOK-505", "planning_to_plan_drafted", "REJECTED")
            result = shepherd_gate.check_gate(505, conn=conn)
        finally:
            conn.close()

        assert result.passed is False

    def test_modern_verdict_wins_over_legacy(self, tmp_db):
        """When both verdicts exist, the modern one is the reported transition."""
        conn = _open(tmp_db)
        try:
            insert_item(conn, id=506, title="Re-shepherded epic", type="epic",
                        status="planned", spec="body")
            _insert_verdict(conn, "YOK-506", "planned_to_ready", "READY",
                            created_at="2026-04-03T12:00:00Z")
            _insert_verdict(conn, "YOK-506", "planning_to_plan_drafted", "CAVEATS",
                            created_at="2026-04-20T12:00:00Z")
            result = shepherd_gate.check_gate(506, conn=conn)
        finally:
            conn.close()

        assert result.passed is True
        assert result.transition == "planning_to_plan_drafted"
        assert result.verdict == "CAVEATS"

    def test_latest_modern_verdict_wins(self, tmp_db):
        """Multiple modern verdicts — the newest (highest id) is returned."""
        conn = _open(tmp_db)
        try:
            insert_item(conn, id=507, title="Re-verdict epic", type="epic",
                        status="planned", spec="body")
            _insert_verdict(conn, "YOK-507", "planning_to_plan_drafted", "CAVEATS",
                            created_at="2026-04-10T12:00:00Z")
            _insert_verdict(conn, "YOK-507", "planning_to_plan_drafted", "READY",
                            created_at="2026-04-20T12:00:00Z")
            result = shepherd_gate.check_gate(507, conn=conn)
        finally:
            conn.close()

        assert result.passed is True
        assert result.verdict == "READY"

    def test_normalize_sun_prefixed_cli_arg(self):
        """CLI accepts YOK-N, plain N, and zero-padded forms."""
        assert shepherd_gate._normalize_item_id("YOK-42") == 42
        assert shepherd_gate._normalize_item_id("yok-042") == 42
        assert shepherd_gate._normalize_item_id("42") == 42
        assert shepherd_gate._normalize_item_id(" 42 ") == 42
        assert shepherd_gate._normalize_item_id("YOK-") is None
        assert shepherd_gate._normalize_item_id("abc") is None
