"""Status-write composition tests for the planned-transition QA gate."""

from __future__ import annotations

import builtins
import sys
from pathlib import Path
from typing import Optional

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.backlog_updates_helpers import _run_authoritative_status_gate
from yoke_core.domain.schema_init_apply import execute_schema_script
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.fixtures.backlog import (
    SCHEMA_DDL,
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)


_EXTRA_DDL = """
CREATE TABLE IF NOT EXISTS project_capabilities (
    id INTEGER PRIMARY KEY,
    project_id INTEGER NOT NULL,
    type TEXT NOT NULL,

    settings TEXT DEFAULT '{}',
    verified_at TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(project_id, type)
);

CREATE TABLE IF NOT EXISTS migration_audit (
    id INTEGER PRIMARY KEY,
    migration_name TEXT NOT NULL,
    status TEXT,
    state TEXT,
    model_name TEXT,
    project_id INTEGER
);
"""


@pytest.fixture
def helper_db(tmp_path: Path):
    db_file = tmp_path / "yoke.db"
    conn = connect_test_db(str(db_file))
    execute_schema_script(conn, SCHEMA_DDL)
    execute_schema_script(conn, _EXTRA_DDL)
    conn.commit()
    yield conn, str(db_file)
    conn.close()


def _seed_item(conn, item_id: int) -> None:
    insert_item(
        conn,
        id=item_id,
        status="plan-drafted",
        db_mutation_profile='{"state":"none"}',
    )


def _seed_req(
    conn,
    item_id: int,
    *,
    verdict: Optional[str] = None,
    waived: bool = False,
) -> int:
    req = insert_qa_requirement(
        conn,
        item_id=item_id,
        qa_kind="simulation",
        qa_phase="verification",
        blocking_mode="blocking",
        waived_at="2026-04-25T00:00:00Z" if waived else None,
    )
    req_id = int(req["id"])
    if verdict is not None:
        insert_qa_run(
            conn,
            qa_requirement_id=req_id,
            verdict=verdict,
            qa_kind="simulation",
        )
    return req_id


def _status_gate(item_id: int, db_path: str, **overrides):
    args = {
        "item_id": item_id,
        "target_status": "planned",
        "db_path": db_path,
        "qa_bypass": False,
        "force": False,
    }
    args.update(overrides)
    return _run_authoritative_status_gate(**args)


class TestPlanSimulationGateComposition:
    def test_planned_with_unsatisfied_blocking_req_returns_unsatisfied(
        self, helper_db
    ) -> None:
        conn, db_path = helper_db
        _seed_item(conn, 80)
        req_id = _seed_req(conn, 80, verdict="fail")
        outcome = _status_gate(80, db_path)
        assert outcome is not None
        assert outcome["error_code"] == "GATE_PLAN_SIM_UNSATISFIED"
        assert "Cannot advance to 'planned'" in outcome["error"]
        assert "no passing run" in outcome["error"]
        assert f"#{req_id}" in outcome["error"]

    def test_planned_with_satisfied_blocking_req_passes(self, helper_db) -> None:
        conn, db_path = helper_db
        _seed_item(conn, 81)
        _seed_req(conn, 81, verdict="pass")
        assert _status_gate(81, db_path) is None

    def test_planned_with_no_requirements_passes(self, helper_db) -> None:
        conn, db_path = helper_db
        _seed_item(conn, 82)
        assert _status_gate(82, db_path) is None

    def test_planned_with_waived_blocking_req_passes(self, helper_db) -> None:
        conn, db_path = helper_db
        _seed_item(conn, 83)
        _seed_req(conn, 83, waived=True)
        assert _status_gate(83, db_path) is None

    def test_planned_with_qa_bypass_skips_gate(self, helper_db) -> None:
        conn, db_path = helper_db
        _seed_item(conn, 84)
        _seed_req(conn, 84, verdict="fail")
        assert _status_gate(84, db_path, qa_bypass=True) is None

    def test_planned_with_force_skips_gate(self, helper_db) -> None:
        conn, db_path = helper_db
        _seed_item(conn, 85)
        _seed_req(conn, 85, verdict="fail")
        assert _status_gate(85, db_path, force=True) is None

    def test_non_planned_target_skips_plan_gate(self, helper_db) -> None:
        conn, db_path = helper_db
        _seed_item(conn, 86)
        _seed_req(conn, 86, verdict="fail")
        outcome = _status_gate(86, db_path, target_status="refined-idea")
        assert outcome is None

    def test_planned_unavailable_helpers_return_unavailable(
        self, helper_db, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn, db_path = helper_db
        _seed_item(conn, 87)

        monkeypatch.delitem(sys.modules, "yoke_core.domain.qa_gates", raising=False)
        original_import = builtins.__import__

        def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
            if name == "yoke_core.domain" and "qa_gates" in (fromlist or ()):
                raise ImportError("simulated missing helpers")
            if name == "yoke_core.domain.qa_gates":
                raise ImportError("simulated missing helpers")
            return original_import(name, globals, locals, fromlist, level)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        outcome = _status_gate(87, db_path)
        assert outcome is not None
        assert outcome["error_code"] == "GATE_PLAN_SIM_UNAVAILABLE"
        assert "QA gate helpers are unavailable" in outcome["error"]
