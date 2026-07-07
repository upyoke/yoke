"""Defense-in-depth: synthetic test writes never reach the live events ledger.

Contract proof:

1. ``YOKE_EVENTS_ISOLATION=1`` autouse fixture refuses writes to live
   Postgres authority at the envelope-build layer (``isolation_gate_blocks``).
2. Postgres test authority is explicit: the configured DSN targets a database
   with the shared ``yoke_test_`` prefix.
3. The CLI emit-event owner (``yoke_core.domain.emit_event``) shares the
   same gate.

If the gate regresses, a test fixture writing a synthetic event row through a
public emit surface could leak into the live ``events`` ledger and contaminate
the synthetic-event Doctor HC. These tests fail loudly so the leak is caught in
CI rather than in a post-incident purge.

The companion data-side delete for historical residue lives in the governed
migration ``yoke_core.db.migrations.purge_synthetic_event_contamination``.
"""

from __future__ import annotations

import os

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.events import (
    SYNTHETIC_SMOKE_FLAG,
    EmitResult,
    emit_event,
    isolation_gate_blocks,
)


# Synthetic-event predicates that the Doctor HC
# ``hc_events_synthetic_contamination`` flags. Tests below assert that no
# in-process emit path lands a row matching any of these predicates against the
# live ledger.
_TEST_SESSION_MARKERS = (
    "test-session-001",
    "pytest-fixture-leak",
    "fixture-spawn-1",
)


def _pin_live_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        db_backend.PG_DSN_ENV,
        "host=/tmp/yoke-live user=yoke dbname=yoke_prod",
    )
    monkeypatch.delenv(db_backend.PG_DSN_FILE_ENV, raising=False)
    monkeypatch.delenv("YOKE_DB", raising=False)


def _pin_test_authority(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(
        db_backend.PG_DSN_ENV,
        "host=/tmp/yoke-test user=yoketest "
        f"dbname={db_backend.POSTGRES_TEST_DB_PREFIX}writer",
    )
    monkeypatch.delenv(db_backend.PG_DSN_FILE_ENV, raising=False)
    monkeypatch.delenv("YOKE_DB", raising=False)


class TestIsolationGateRefusesLiveWrites:
    """The native emitter refuses live-authority writes under test isolation."""

    @pytest.mark.parametrize("session_id", _TEST_SESSION_MARKERS)
    def test_isolation_refuses_test_session_marker(self, session_id, monkeypatch):
        """``emit_event`` returns ``isolation_gate_refused`` for test markers."""
        _pin_live_authority(monkeypatch)

        # Isolation is autouse via runtime/api/fixtures/runtime.py -- assert
        # the env contract is intact so a future regression that drops the
        # autouse is loud.
        assert os.environ.get("YOKE_EVENTS_ISOLATION") == "1"

        result: EmitResult = emit_event(
            "TestSyntheticEvent",
            event_kind="lifecycle",
            event_type="test",
            source_type="backend",
            session_id=session_id,
            project="yoke",
        )

        assert result.ok is False
        assert result.reason == "isolation_gate_refused"


class TestPostgresTestAuthorityEscapeHatch:
    """Postgres test databases remain the explicit write-isolation escape."""

    def test_test_db_authority_opens_gate(self, monkeypatch):
        _pin_test_authority(monkeypatch)

        assert (
            isolation_gate_blocks(
                db_path=None,
                anomaly_flags=None,
                has_explicit_conn=False,
            )
            is False
        )


class TestSyntheticSmokeEscapeHatch:
    """The ``synthetic_smoke`` lineage marker remains the documented opt-in."""

    def test_smoke_flag_opens_gate_for_live_authority(self, monkeypatch):
        _pin_live_authority(monkeypatch)

        assert (
            isolation_gate_blocks(
                db_path=None,
                anomaly_flags=SYNTHETIC_SMOKE_FLAG,
                has_explicit_conn=False,
            )
            is False
        )


class TestIsolationReasonDistinguishesLiveFromTestAuthority:
    """Pin the two distinct isolation outcomes for Postgres authority."""

    def test_live_authority_returns_isolation_gate_refused(self, monkeypatch):
        _pin_live_authority(monkeypatch)

        assert os.environ.get("YOKE_EVENTS_ISOLATION") == "1"
        result: EmitResult = emit_event(
            "TestSyntheticEvent",
            event_kind="lifecycle",
            event_type="test",
            source_type="backend",
            session_id="test-live-refusal-1",
            project="yoke",
        )
        assert result.ok is False
        assert result.reason == "isolation_gate_refused"

    def test_test_authority_does_not_depend_on_file_path_identity(
        self, monkeypatch
    ):
        _pin_test_authority(monkeypatch)

        assert (
            isolation_gate_blocks(
                db_path="/irrelevant/path/token.db",
                anomaly_flags=None,
                has_explicit_conn=False,
            )
            is False
        )
