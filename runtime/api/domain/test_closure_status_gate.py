"""Closure is evaluated on every authoritative write to ``done``."""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest

from runtime.api.domain.check_hard_blocks_test_helpers import (
    apply_hard_block_schema,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_core.domain import backlog_authoritative_status_gate
from yoke_core.domain import closure_status_gate as mod
from yoke_core.domain import db_backend
from yoke_core.domain.dependency_types import GatePoint


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    with init_test_db(tmp_path, apply_schema=apply_hard_block_schema) as path:
        monkeypatch.setenv("YOKE_DB", path)
        yield path


def _insert_item(db_path: str, item_id: int, title: str, status: str = "idea") -> None:
    conn = connect_test_db(db_path)
    p = _p(conn)
    conn.execute(
        "INSERT INTO items (id, title, status, priority, "
        "project_id, project_sequence, merged_at) "
        f"VALUES ({p}, {p}, {p}, 'medium', 1, {p}, NULL)",
        (item_id, title, status, item_id),
    )
    conn.commit()
    conn.close()


def _insert_dep(
    db_path: str,
    dependent: int,
    blocking: int,
    gate_point: str,
    satisfaction: str,
) -> None:
    conn = connect_test_db(db_path)
    p = _p(conn)
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item_id, blocking_item_id, gate_point, satisfaction) "
        f"VALUES ({p}, {p}, {p}, {p})",
        (dependent, blocking, gate_point, satisfaction),
    )
    conn.commit()
    conn.close()


def test_status_write_helper_is_a_no_op_off_done():
    assert (
        mod.evaluate_for_status_write(
            item_id=1, target_status="implementing", conn=object()
        )
        is None
    )


def test_evaluate_refuses_an_unsatisfied_closure_edge(db_path):
    _insert_item(db_path, 42, "Dependent", status="release")
    _insert_item(db_path, 10, "Blocker", status="idea")
    _insert_dep(db_path, 42, 10, "closure", "status:done")
    conn = connect_test_db(db_path)
    try:
        failure = mod.evaluate(item_id=42, conn=conn)
    finally:
        conn.close()
    assert failure is not None
    assert failure["error_code"] == "GATE_CLOSURE_UNSATISFIED"
    assert "YOK-10" in failure["error"]
    assert "blocks closure" in failure["error"]
    assert "status reaches done" in failure["error"]
    assert "items.blocked" in failure["remediation_hint"]


def test_evaluate_ignores_an_unsatisfied_activation_edge(db_path):
    _insert_item(db_path, 42, "Dependent", status="release")
    _insert_item(db_path, 10, "Blocker", status="idea")
    _insert_dep(db_path, 42, 10, "activation", "status:done")
    conn = connect_test_db(db_path)
    try:
        assert mod.evaluate(item_id=42, conn=conn) is None
    finally:
        conn.close()


def test_evaluate_passes_when_the_closure_edge_is_satisfied(db_path):
    _insert_item(db_path, 42, "Dependent", status="release")
    _insert_item(db_path, 10, "Blocker", status="done")
    _insert_dep(db_path, 42, 10, "closure", "status:done")
    conn = connect_test_db(db_path)
    try:
        assert mod.evaluate(item_id=42, conn=conn) is None
    finally:
        conn.close()


def test_evaluate_passes_when_the_registry_is_absent(monkeypatch):
    monkeypatch.setattr(mod, "_table_exists", lambda conn, table: False)
    assert mod.evaluate(item_id=7, conn=object()) is None


def test_evaluate_fail_closes_when_the_evaluator_raises(monkeypatch):
    monkeypatch.setattr(mod, "_table_exists", lambda conn, table: True)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("control plane unread")

    monkeypatch.setattr(
        "yoke_core.domain.check_hard_blocks.evaluate_blockers",
        _boom,
    )
    failure = mod.evaluate(item_id=7, conn=object())
    assert failure is not None
    assert failure["error_code"] == "GATE_CLOSURE_UNSATISFIED"
    assert "could not be evaluated" in failure["error"]


def test_evaluate_calls_the_shared_evaluator_at_closure(monkeypatch):
    seen: list[tuple[int, str]] = []
    monkeypatch.setattr(mod, "_table_exists", lambda conn, table: True)

    def _record(item_id, gate_filter=None, conn=None):
        seen.append((item_id, gate_filter))
        return []

    monkeypatch.setattr(
        "yoke_core.domain.check_hard_blocks.evaluate_blockers",
        _record,
    )
    assert mod.evaluate(item_id=9, conn=object()) is None
    assert seen == [(9, GatePoint.CLOSURE.value)]


def test_composer_refuses_unsatisfied_closure_even_with_force(monkeypatch):
    monkeypatch.setattr(
        backlog_authoritative_status_gate,
        "load_item_workflow_runtime",
        lambda conn, item_id: SimpleNamespace(
            workflow_id="issue",
            gates_for_stage=lambda status: (),
        ),
    )
    monkeypatch.setattr(
        backlog_authoritative_status_gate,
        "terminal_transition_result",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(mod, "_table_exists", lambda conn, table: True)
    monkeypatch.setattr(
        "yoke_core.domain.check_hard_blocks.evaluate_blockers",
        lambda item_id, gate_filter=None, conn=None: (
            ["BLOCKED|YOK-9|idea|Ship it|closure|status:done|blocker is idea"]
            if gate_filter == GatePoint.CLOSURE.value
            else []
        ),
    )
    result = backlog_authoritative_status_gate._run_authoritative_status_gate(
        item_id=7,
        target_status="done",
        db_path="",
        qa_bypass=False,
        force=True,
        conn=object(),
    )
    assert result is not None
    assert result["error_code"] == "GATE_CLOSURE_UNSATISFIED"
    assert "YOK-9" in result["error"]


def test_composer_source_always_calls_the_closure_helper():
    source = inspect.getsource(backlog_authoritative_status_gate)
    assert "evaluate_for_status_write" in source
