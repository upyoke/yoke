"""Expired read handlers unwind and retain a named, observable refusal."""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from psycopg.pq import TransactionStatus

from yoke_contracts.api.function_call import HandlerOutcome
from yoke_contracts.read_deadline import (
    ReadDeadlineExceeded,
    active,
    read_budget,
    remaining_seconds,
)
from yoke_core.domain import function_read_deadline as deadline
from yoke_core.domain.bounded_database import BudgetConnection
from runtime.api.domain.test_yoke_function_dispatch import (
    _DispatcherTestBase,
    _Req,
    _Resp,
    _make_request,
    _stable_kwargs,
)
from yoke_core.domain.yoke_function_registry import register
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain import yoke_function_dispatch_events as events


@pytest.mark.parametrize("threaded", [False, True])
def test_overrun_read_is_refused_without_tracing_the_handler(monkeypatch, threaded):
    monkeypatch.setattr(deadline, "FUNCTION_RESPONSE_TIMEOUT_SECONDS", 0.03)
    monkeypatch.setattr(deadline, "READ_RESPONSE_RESERVE_SECONDS", 0)
    traces = []

    def handler(request):
        traces.append(sys.gettrace())
        time.sleep(0.05)
        return HandlerOutcome(primary_success=True)

    def run():
        trace = sys.gettrace()
        result = deadline.invoke_handler(
            SimpleNamespace(
                side_effects=(),
                function_id="qa.plan.list",
                handler=handler,
            ),
            _make_request("qa.plan.list"),
        )
        assert result.error.code == "read_deadline_exceeded"
        assert result.error.recovery_hint is None
        assert "--" not in result.error.message
        assert not active()
        assert traces == [trace]

    if threaded:
        with ThreadPoolExecutor(max_workers=1) as executor:
            executor.submit(run).result(timeout=2)
    else:
        run()


@pytest.mark.parametrize("effects", [("database",), ("event_emit",)])
def test_mutation_keeps_its_handler_without_a_read_budget(effects):
    observed = []

    def handler(request):
        observed.append(active())
        return HandlerOutcome(primary_success=True)

    result = deadline.invoke_handler(
        SimpleNamespace(
            side_effects=effects,
            function_id="items.create",
            handler=handler,
        ),
        _make_request("items.create"),
    )
    assert result.primary_success
    assert observed == [False]


class _FakePostgres:
    """Tracks transaction state the way psycopg reports it."""

    def __init__(self, statements, *, fail_with=None):
        self.autocommit = False
        self.info = SimpleNamespace(transaction_status=TransactionStatus.IDLE)
        self._statements = statements
        self._fail_with = fail_with

    def execute(self, sql, params=()):
        self._statements.append((sql, params))
        self.info.transaction_status = TransactionStatus.INTRANS

    def commit(self):
        self.info.transaction_status = TransactionStatus.IDLE

    def cursor(self):
        conn = self

        class Cursor:
            def execute(self, sql, params=()):
                conn.execute(sql, params)
                if conn._fail_with:
                    raise conn._fail_with

        return Cursor()


_TIMEOUT_SETUP = "SELECT set_config('statement_timeout', %s, %s)"


def _budgeted(native):
    return BudgetConnection(
        native,
        remaining=lambda: remaining_seconds(30),
        driver_call=deadline.driver_call,
    )


def test_sql_timeout_is_the_remaining_request_budget():
    statements = []
    failure = Exception("statement cancelled")
    failure.sqlstate = "57014"

    with read_budget(0.5):
        conn = _budgeted(_FakePostgres(statements, fail_with=failure))
        with pytest.raises(ReadDeadlineExceeded):
            conn.execute("SELECT pg_sleep(1)")
    assert statements[0][0] == _TIMEOUT_SETUP
    assert 0 < int(statements[0][1][0][:-2]) <= 500
    assert statements[0][1][1] is True
    assert not active()


def test_timeout_is_armed_once_per_transaction_not_per_statement():
    statements = []
    with read_budget(5):
        conn = _budgeted(_FakePostgres(statements))
        for _ in range(5):
            conn.execute("SELECT 1")
        conn.commit()
        conn.execute("SELECT 2")
    setups = [sql for sql, _ in statements if sql == _TIMEOUT_SETUP]
    assert len(statements) == 8
    assert len(setups) == 2
    assert statements[0][0] == _TIMEOUT_SETUP
    assert statements[6][0] == _TIMEOUT_SETUP


def test_autocommit_session_is_armed_once():
    statements = []
    native = _FakePostgres(statements)
    native.autocommit = True
    with read_budget(5):
        conn = _budgeted(native)
        for _ in range(3):
            conn.execute("SELECT 1")
    assert [sql for sql, _ in statements].count(_TIMEOUT_SETUP) == 1
    assert statements[0][1][1] is False


class TestDeadlineEvent(_DispatcherTestBase):
    def test_dispatch_records_refused_read_on_called_event(self):
        completed = []

        def handler(request):
            time.sleep(0.05)
            completed.append(True)
            return HandlerOutcome(primary_success=True)

        register("test.expired_read", handler, _Req, _Resp, **_stable_kwargs())
        with (
            patch.object(deadline, "FUNCTION_RESPONSE_TIMEOUT_SECONDS", 0.03),
            patch.object(deadline, "READ_RESPONSE_RESERVE_SECONDS", 0),
        ):
            response = dispatch(_make_request("test.expired_read"))
        assert response.error.code == "read_deadline_exceeded"
        called = [
            row
            for row in events.emit_event.calls
            if row["args"] and row["args"][0] == "YokeFunctionCalled"
        ]
        assert len(called) == 1
        assert called[0]["kwargs"]["outcome"] == "failed"
        assert called[0]["kwargs"]["context"]["error_code"] == "read_deadline_exceeded"
        assert completed == [True]


@pytest.fixture(scope="module")
def postgres_dsn():
    from runtime.api.fixtures import pg_testdb

    name = pg_testdb.create_test_database()
    try:
        yield pg_testdb.dsn_for_test_database(name)
    finally:
        pg_testdb.drop_test_database(name)


def test_postgres_read_arms_one_timeout_for_many_statements(postgres_dsn):
    from yoke_core.domain import db_backend

    setups = []

    def counting_driver_call(method, *args, **kwargs):
        if args and args[0] == _TIMEOUT_SETUP:
            setups.append(args[1][0])
        return deadline.driver_call(method, *args, **kwargs)

    with db_backend.bound_pg_dsn(postgres_dsn):
        with db_backend.connect() as native:
            with read_budget(5):
                conn = BudgetConnection(
                    native,
                    remaining=lambda: remaining_seconds(30),
                    driver_call=counting_driver_call,
                )
                for _ in range(5):
                    conn.execute("SELECT 1")
                timeout = conn.execute("SHOW statement_timeout").fetchone()[0]
    assert len(setups) == 1
    assert timeout != "0"


def test_postgres_stops_the_query_before_the_handler_can_finish(postgres_dsn):
    from yoke_core.domain import db_backend

    completed = []
    started = time.monotonic()
    with db_backend.bound_pg_dsn(postgres_dsn):
        # Open outside the short test budget so this proves SQL cancellation,
        # independently of database startup and local socket acquisition.
        with db_backend.connect() as native:
            with pytest.raises(ReadDeadlineExceeded):
                with read_budget(0.15):
                    conn = BudgetConnection(
                        native,
                        remaining=lambda: remaining_seconds(30),
                        driver_call=deadline.driver_call,
                    )
                    conn.execute("SELECT pg_sleep(2)")
                    completed.append(True)
    assert completed == []
    assert time.monotonic() - started < 2
