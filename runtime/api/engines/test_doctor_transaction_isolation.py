"""Doctor roster transaction-isolation regression tests."""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from unittest.mock import patch

from yoke_core.engines import doctor as doctor_engine
from yoke_core.engines.doctor_registry_types import HealthCheck


class _AbortedTransactionConn:
    """PostgreSQL-state double: statement errors poison until rollback."""

    def __init__(self):
        self.aborted = False
        self.rollback_count = 0

    def execute(self, statement, *_args):
        if self.aborted:
            raise RuntimeError(
                "current transaction is aborted, commands ignored until "
                "end of transaction block"
            )
        if statement == "synthetic broken query":
            self.aborted = True
            raise RuntimeError("synthetic query failed")
        return self

    def fetchone(self):
        return None

    def rollback(self):
        self.rollback_count += 1
        self.aborted = False

    def close(self):
        pass


def _query_error(conn, _args, _rec):
    conn.execute("synthetic broken query")


def _query_after_error(conn, _args, rec):
    conn.execute("synthetic healthy query")
    rec.record("HC-after-error", "After-error HC", "PASS", "query ran")


def test_failing_query_cannot_poison_the_following_check() -> None:
    conn = _AbortedTransactionConn()
    checks = [
        HealthCheck(slug="query-error", name="Query-error HC", fn=_query_error),
        HealthCheck(
            slug="after-error", name="After-error HC", fn=_query_after_error,
        ),
    ]
    with patch("yoke_core.engines.doctor.HEALTH_CHECKS", checks):
        with patch("yoke_core.engines.doctor.connect", return_value=conn):
            output = io.StringIO()
            with redirect_stdout(output):
                rc = doctor_engine.run_checks(doctor_engine.DoctorArgs(
                    quick=True,
                    project="yoke",
                    runtime="hosted",
                ))

    report = output.getvalue()
    assert rc == 1
    assert "HC-internal-error" in report
    assert "synthetic query failed" in report
    assert "HC-after-error: PASS" in report
    assert "current transaction is aborted" not in report
    assert conn.rollback_count >= 4
