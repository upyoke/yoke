"""Tests for the ``ouroboros.field_note.append`` handler.

Covers durable-row + telemetry-event ordering, the four-kind vocabulary
(``failed``, ``new``, ``unclear``, ``observation``), payload validation,
and the failure-mode contracts: durable-write failure surfaces
``emit_failed`` (no event emitted); event-failure after a successful
durable write still reports ``primary_success=True`` with
``event_id=None`` (durable store is authoritative).

Evidence strings here stay short and concrete. Field-note evidence can
use ordinary diagnostic language.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.events import EmitResult
from yoke_core.domain.handlers import ouroboros_field_note as _ofn
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from runtime.api.fixtures.file_test_db import init_test_db


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Backend-aware fresh-schema test DB; yield a ``db_path`` token.

    On Postgres this is a disposable per-test database
    (``YOKE_PG_DSN`` repointed for the context). The setenv stays inside
    the :func:`init_test_db` context so handler code resolves the same DB.
    """
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _build_request(
    *,
    kind: str = "observation",
    evidence: str = "observation: stale doc reference noticed",
    correlation_id: str | None = None,
    target_kind: str = "global",
    session_id: str = "session-test-1",
    actor_id: str | None = None,
) -> FunctionCallRequest:
    payload: dict = {"kind": kind, "evidence": evidence}
    if correlation_id is not None:
        payload["correlation_id"] = correlation_id
    actor_kwargs: dict = {"session_id": session_id}
    if actor_id is not None:
        actor_kwargs["actor_id"] = actor_id
    return FunctionCallRequest(
        function="ouroboros.field_note.append",
        actor=ActorContext(**actor_kwargs),
        target=TargetRef(kind=target_kind),
        payload=payload,
    )


def _ok_emit_result(event_id: str = "evt-test-1") -> EmitResult:
    return EmitResult(ok=True, event_id=event_id, reason="", envelope=None)


def _failed_emit_result(reason: str = "events_table_missing") -> EmitResult:
    return EmitResult(ok=False, event_id=None, reason=reason, envelope=None)


class TestHappyPath:
    def test_handle_append_happy_path_observation_kind(self, tmp_db: str):
        with patch.object(
            _ofn._events, "emit_event", return_value=_ok_emit_result(),
        ):
            outcome = _ofn.handle_append(_build_request())

        assert outcome.primary_success is True
        assert outcome.error is None
        entry_id = outcome.result_payload["entry_id"]
        assert isinstance(entry_id, str) and entry_id
        assert outcome.result_payload["event_id"] == "evt-test-1"
        assert outcome.result_payload["kind"] == "observation"
        assert outcome.result_payload["evidence_preview"].startswith(
            "observation:"
        )
        assert outcome.result_payload["github_sync"] == "not_applicable"
        assert outcome.result_payload["body_sync_mode"] == "not_applicable"
        assert outcome.result_payload["body_sync_elapsed_ms"] == 0

        with connect(tmp_db) as conn:
            p = _p(conn)
            row = conn.execute(
                f"SELECT category, body FROM ouroboros_entries WHERE id={p}",
                (int(entry_id),),
            ).fetchone()
        assert row is not None
        assert row["category"] == "field-note-observation"
        assert row["body"] == "observation: stale doc reference noticed"


class TestFourKinds:
    @pytest.mark.parametrize(
        "kind,evidence",
        [
            ("failed", "recipe R-OP-04 produced port 8000 instead of 8765"),
            ("new", "no recipe exists for harness X provisioning"),
            ("unclear", "purpose unclear for R-CL-02 in skill polish"),
            ("observation", "observation: stale doc reference noticed"),
        ],
    )
    def test_handle_append_all_four_kinds(
        self, tmp_db: str, kind: str, evidence: str,
    ):
        with patch.object(
            _ofn._events, "emit_event", return_value=_ok_emit_result(),
        ):
            outcome = _ofn.handle_append(
                _build_request(kind=kind, evidence=evidence),
            )

        assert outcome.primary_success is True
        entry_id = outcome.result_payload["entry_id"]
        assert isinstance(entry_id, str) and entry_id

        with connect(tmp_db) as conn:
            p = _p(conn)
            row = conn.execute(
                f"SELECT category, body FROM ouroboros_entries WHERE id={p}",
                (int(entry_id),),
            ).fetchone()
        assert row["category"] == f"field-note-{kind}"
        assert row["body"] == evidence


class TestValidationFailures:
    def test_handle_append_rejects_unknown_kind(self, tmp_db: str):
        request = FunctionCallRequest(
            function="ouroboros.field_note.append",
            actor=ActorContext(session_id="s"),
            target=TargetRef(kind="global"),
            payload={"kind": "compat-broken", "evidence": "x"},
        )
        outcome = _ofn.handle_append(request)
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "invalid_payload"

    def test_handle_append_rejects_empty_evidence(self, tmp_db: str):
        request = FunctionCallRequest(
            function="ouroboros.field_note.append",
            actor=ActorContext(session_id="s"),
            target=TargetRef(kind="global"),
            payload={"kind": "observation", "evidence": ""},
        )
        outcome = _ofn.handle_append(request)
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "invalid_payload"

    def test_handle_append_rejects_oversized_evidence(self, tmp_db: str):
        request = _build_request(
            evidence="x" * (_ofn.EVIDENCE_MAX_CHARS + 1),
        )
        outcome = _ofn.handle_append(request)
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "invalid_payload"

    def test_handle_append_rejects_non_global_target_kind(self, tmp_db: str):
        request = _build_request(target_kind="item")
        request.target.item_id = 1
        outcome = _ofn.handle_append(request)
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "invalid_payload"
        assert "global" in outcome.error.message


class TestDurableAndEventWrite:
    def test_handle_append_writes_durable_row_and_event(self, tmp_db: str):
        emit_calls: list[dict] = []

        def fake_emit(event_name, **kwargs):
            emit_calls.append({"event_name": event_name, **kwargs})
            return _ok_emit_result("e-1")

        with connect(tmp_db) as conn:
            rows_before = conn.execute(
                "SELECT COUNT(*) FROM ouroboros_entries"
            ).fetchone()[0]

        with patch.object(_ofn._events, "emit_event", side_effect=fake_emit):
            outcome = _ofn.handle_append(_build_request())

        assert outcome.primary_success is True
        assert len(emit_calls) == 1
        assert emit_calls[0]["event_name"] == "OuroborosFieldNoteAppended"
        assert emit_calls[0]["context"]["kind"] == "observation"
        assert "entry_id" in emit_calls[0]["context"]

        with connect(tmp_db) as conn:
            rows_after = conn.execute(
                "SELECT COUNT(*) FROM ouroboros_entries"
            ).fetchone()[0]
        assert rows_after == rows_before + 1


class TestEventFailureAfterDurableWrite:
    def test_handle_append_event_failure_after_durable_row_still_success(
        self, tmp_db: str,
    ):
        with patch.object(
            _ofn._events,
            "emit_event",
            return_value=_failed_emit_result("events_table_missing"),
        ):
            outcome = _ofn.handle_append(_build_request())

        assert outcome.primary_success is True
        assert outcome.error is None
        assert outcome.result_payload["event_id"] is None
        entry_id = outcome.result_payload["entry_id"]
        assert isinstance(entry_id, str) and entry_id

        with connect(tmp_db) as conn:
            p = _p(conn)
            row = conn.execute(
                f"SELECT id FROM ouroboros_entries WHERE id={p}",
                (int(entry_id),),
            ).fetchone()
        assert row is not None


class TestDurableWriteFailure:
    def test_handle_append_durable_write_failure_returns_emit_failed(
        self, tmp_db: str,
    ):
        emit_calls: list[dict] = []

        def fake_emit(*args, **kwargs):
            emit_calls.append({"args": args, "kwargs": kwargs})
            return _ok_emit_result()

        def boom(*args, **kwargs):
            raise RuntimeError("simulated insert failure")

        with connect(tmp_db) as conn:
            rows_before = conn.execute(
                "SELECT COUNT(*) FROM ouroboros_entries"
            ).fetchone()[0]

        with patch.object(_ofn, "cmd_insert_entry", side_effect=boom):
            with patch.object(
                _ofn._events, "emit_event", side_effect=fake_emit,
            ):
                outcome = _ofn.handle_append(_build_request())

        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "emit_failed"
        assert len(emit_calls) == 0

        with connect(tmp_db) as conn:
            rows_after = conn.execute(
                "SELECT COUNT(*) FROM ouroboros_entries"
            ).fetchone()[0]
        assert rows_after == rows_before


class TestRegistrationContract:
    def test_registers_one_entry(self):
        assert len(_ofn.REGISTRATIONS) == 1
        entry = _ofn.REGISTRATIONS[0]
        assert entry["function_id"] == "ouroboros.field_note.append"
        assert entry["target_kinds"] == ["global"]
        assert _ofn.FIELD_NOTE_EVENT_NAME in entry["emitted_event_names"]
        assert entry["claim_required_kind"] is None
        assert entry["adapter_status"] == "live"
        assert entry["ambient_session_required"] is False
        assert entry["owner_module"] == (
            "yoke_core.domain.handlers.ouroboros_field_note"
        )

    def test_dispatcher_round_trip(self, tmp_db: str):
        from yoke_core.domain.handlers.__init_register__ import (
            register_all_handlers,
        )
        from yoke_core.domain.yoke_function_dispatch import dispatch
        from yoke_core.domain.yoke_function_registry import (
            reset_registry_for_tests,
        )

        reset_registry_for_tests()
        register_all_handlers()

        request = _build_request(
            kind="new",
            evidence="no recipe exists for foo",
            session_id="ambient-session-id",
        )
        with patch.object(
            _ofn._events, "emit_event", return_value=_ok_emit_result("e-rt"),
        ):
            response = dispatch(
                request, ambient_session_id="ambient-session-id",
            )

        assert response.success is True
        assert response.function == "ouroboros.field_note.append"
        assert response.result["event_id"] == "e-rt"
        assert response.result["kind"] == "new"
        assert response.result["entry_id"]
