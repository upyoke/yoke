"""Dispatch-chain diagnostics preserve read failures and never advance state."""

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import chain_head_freshness as freshness
from yoke_core.domain import dispatch_chain_head as heads
from yoke_core.domain import epic_dispatch
from yoke_core.domain.handlers import workflow_item_epic_task_ops as handlers
from yoke_core.domain.handlers.epic_task_operation_models import ChainReadResponse


@pytest.fixture
def source(monkeypatch):
    state = SimpleNamespace(
        chains=[{"queue": "[3, 4]", "current_index": 0, "current_task": "3"}],
        tasks=[{"status": "implementing"}],
        calls=[],
    )

    def rows(conn, sql, params):
        state.calls.append((sql, params))
        return state.chains if "epic_dispatch_chains" in sql else state.tasks

    monkeypatch.setattr(heads, "query_rows", rows)
    monkeypatch.setattr(freshness, "get_seconds", lambda _key, default: default)
    monkeypatch.setattr(freshness, "_prior_session_for_epic", lambda *_args: None)
    monkeypatch.setattr(freshness, "_task_last_activity_at", lambda *_args, **_kw: None)
    monkeypatch.setattr(
        "yoke_core.domain.sessions_queries_lookup.get_claim_for_work_unit",
        lambda *_args, **_kw: None,
    )
    state.conn = Mock()
    return state


@pytest.mark.parametrize("status", ["implementing", "reviewing-implementation"])
@pytest.mark.parametrize("decision", ["resumable", "busy", "blocked"])
def test_actual_freshness_outcomes(source, monkeypatch, status, decision):
    source.tasks[0]["status"] = status
    if decision == "busy":
        monkeypatch.setattr(
            freshness,
            "_task_last_activity_at",
            lambda *_a, **_kw: datetime.now(timezone.utc),
        )
    elif decision == "blocked":
        monkeypatch.setattr(
            "yoke_core.domain.sessions_queries_lookup.get_claim_for_work_unit",
            lambda *_a, **_kw: {"session_id": "other-session"},
        )
    result = heads.read_head_dispatch(source.conn, 42, "caller", "lane")
    assert result[0]["decision"] == decision
    assert result[0]["task_num"] == 3
    assert result[0]["holder_session_id"] == (
        "other-session" if decision == "blocked" else None
    )
    assert source.calls[0][1] == (42, "lane")
    assert source.calls[1][1] == (42, 3)
    assert all(sql.startswith("SELECT") for sql, _ in source.calls)


@pytest.mark.parametrize(
    "changes",
    [
        {"current_index": -1},
        {"current_index": "invalid"},
        {"current_index": 0.5},
        {"current_index": True},
        {"queue": "[true]"},
        {"queue": "[3.5]"},
        {"queue": '["invalid"]'},
        {"current_task": "4"},
        {"current_task": "wrong"},
    ],
)
def test_inconsistent_heads_are_unknown(source, changes):
    source.chains[0].update(changes)
    result = heads.read_head_dispatch(source.conn, 42, "caller")
    assert result[0]["decision"] == "unknown"
    assert "chain_head_inconsistent" in result[0]["reason"]


@pytest.mark.parametrize("tasks", [[], [{"status": "implementing"}] * 2])
def test_missing_or_ambiguous_same_epic_task_is_unknown(source, tasks):
    source.tasks = tasks
    result = heads.read_head_dispatch(source.conn, 42, "caller")
    assert result[0]["decision"] == "unknown"
    assert "expected one same-epic task" in result[0]["reason"]


@pytest.mark.parametrize(
    "queue,index,status",
    [
        ("[]", 0, "implementing"),
        ("[3]", 1, "implementing"),
        ("[3]", 0, "done"),
        ("[3]", 0, "planned"),
    ],
)
def test_empty_exhausted_and_not_in_flight_have_no_diagnostic(
    source, queue, index, status
):
    source.chains[0].update(queue=queue, current_index=index)
    source.tasks[0]["status"] = status
    assert heads.read_head_dispatch(source.conn, 42, "caller") == []


def test_missing_caller_identity_is_unknown(source):
    result = heads.read_head_dispatch(source.conn, 42, None)
    assert result[0]["decision"] == "unknown"
    assert "caller_identity_unavailable" in result[0]["reason"]


def test_evaluator_failure_is_unknown(source, monkeypatch):
    monkeypatch.setattr(
        heads,
        "evaluate_chain_head_freshness",
        Mock(side_effect=RuntimeError("unavailable")),
    )
    assert (
        heads.read_head_dispatch(source.conn, 42, "caller")[0]["decision"] == "unknown"
    )


@pytest.mark.parametrize("read", ["chain", "task", "claim"])
def test_unavailable_reads_are_unknown(source, monkeypatch, read):
    if read == "claim":
        monkeypatch.setattr(
            "yoke_core.domain.sessions_queries_lookup.get_claim_for_work_unit",
            Mock(side_effect=RuntimeError("unavailable")),
        )
    else:
        original = heads.query_rows

        def fail(conn, sql, params):
            if ("epic_dispatch_chains" in sql) == (read == "chain"):
                raise RuntimeError("unavailable")
            return original(conn, sql, params)

        monkeypatch.setattr(heads, "query_rows", fail)
    result = heads.read_head_dispatch(source.conn, 42, "caller")
    assert result[0]["decision"] == "unknown"
    assert "unavailable" in result[0]["reason"]


def test_swallowed_nested_read_failure_is_unknown(source, monkeypatch):
    source.conn.execute.side_effect = RuntimeError("unavailable")

    def tolerant_evaluator(*_args, conn, **_kwargs):
        try:
            conn.execute("SELECT last_heartbeat FROM harness_sessions")
        except RuntimeError:
            pass
        return SimpleNamespace(
            status="resumable",
            rationale="absent",
            evidence=SimpleNamespace(holder_session_id="caller"),
        )

    monkeypatch.setattr(heads, "evaluate_chain_head_freshness", tolerant_evaluator)
    result = heads.read_head_dispatch(source.conn, 42, "caller")
    assert result[0]["decision"] == "unknown"
    assert result[0]["holder_session_id"] == "caller"


def test_list_returns_one_row_per_eligible_chain(source):
    source.chains *= 2
    result = heads.read_head_dispatch(source.conn, 42, "caller")
    assert len(result) == 2
    assert source.calls[0][1] == (42,)


@pytest.mark.parametrize("raw", ["[3, 4]", '"3,4"', "3,4", [3, 4]])
def test_advance_and_diagnostics_share_queue_parser(source, monkeypatch, raw):
    parser = Mock(wraps=epic_dispatch.parse_dispatch_queue)
    monkeypatch.setattr(epic_dispatch, "parse_dispatch_queue", parser)
    monkeypatch.setattr(heads, "parse_dispatch_queue", parser)
    source.chains[0]["queue"] = raw
    assert heads.read_head_dispatch(source.conn, 42, "caller")[0]["task_num"] == 3
    monkeypatch.setattr(
        epic_dispatch, "query_one", lambda *_a: {"queue": raw, "current_index": 0}
    )
    assert epic_dispatch.dispatch_chain_advance(source.conn, "42", "lane") == "1|4"
    assert parser.call_count == 2


@pytest.mark.parametrize("operation", ["get", "list"])
def test_handlers_compose_authenticated_caller_and_typed_response(
    source, monkeypatch, operation
):
    @contextmanager
    def connection():
        yield source.conn

    monkeypatch.setattr(handlers, "_open_connection", connection)
    monkeypatch.setattr(handlers, "public_epic_pipe_rows", lambda _c, _e, body: body)
    monkeypatch.setattr(
        handlers.epic, "dispatch_chain_" + operation, lambda *_a: "pipe body"
    )
    request = FunctionCallRequest(
        function="workflow_item.epic_dispatch_chain." + operation,
        actor=ActorContext(session_id="caller"),
        target=TargetRef(kind="epic_task", epic_id=42),
        payload={"worktree": "lane"} if operation == "get" else {},
    )
    outcome = getattr(handlers, "handle_dispatch_chain_" + operation)(request)
    result = ChainReadResponse.model_validate(outcome.result_payload)
    assert outcome.primary_success
    assert result.body == "pipe body"
    assert result.head_dispatch[0].decision == "resumable"
    registration = next(
        r for r in handlers.REGISTRATIONS if r["function_id"] == request.function
    )
    assert registration["response_model"] is ChainReadResponse


def test_strict_task_activity_read_does_not_hide_database_failure(monkeypatch):
    conn = Mock()
    conn.execute.side_effect = RuntimeError("unavailable")
    monkeypatch.setattr(
        freshness.db_backend, "operational_error_types", lambda _conn: (RuntimeError,)
    )
    with pytest.raises(RuntimeError, match="unavailable"):
        freshness._task_last_activity_at(conn, 42, 3, strict_reads=True)
    conn.rollback.assert_not_called()


@pytest.mark.parametrize("holder", [None, "another-session"])
def test_diagnostics_with_real_postgres_reads(holder, monkeypatch):
    from runtime.api.test_dependency_schema import create_dependency_test_db
    from yoke_core.domain.work_claim_targets import make_item_target

    conn = create_dependency_test_db()
    try:
        conn.execute(
            "CREATE TABLE epic_dispatch_chains (id INTEGER PRIMARY KEY, epic_id INTEGER, item_worktree_id INTEGER, queue TEXT, current_index INTEGER, current_task TEXT)"
        )
        conn.execute(
            "CREATE TABLE epic_tasks (epic_id INTEGER, task_num INTEGER, status TEXT, last_activity_at TEXT)"
        )
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO items (id, title, created_at, updated_at) VALUES (42, 'epic', %s, %s)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO item_worktrees (id, item_id, branch, lane_role, created_at, updated_at) VALUES (1, 42, 'lane', 'worker', %s, %s)",
            (now, now),
        )
        conn.execute(
            "INSERT INTO epic_dispatch_chains VALUES (1, 42, 1, '[3]', 0, '3')"
        )
        conn.execute("INSERT INTO epic_tasks VALUES (42, 3, 'implementing', NULL)")
        if holder:
            conn.execute(
                "INSERT INTO work_claims (session_id, target_kind, scope, claimed_at) VALUES (%s, 'item', %s, %s)",
                (
                    holder,
                    make_item_target(42).scope_json(),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
        conn.commit()
        monkeypatch.setattr(freshness, "get_seconds", lambda _key, default: default)
        result = heads.read_head_dispatch(conn, 42, "caller", "lane")
        assert result[0]["decision"] == ("blocked" if holder else "resumable")
        assert result[0]["holder_session_id"] == holder
    finally:
        conn.close()
