"""Tests for the ``workflow_item.epic_task`` state handlers + registration shape.

Covers ``body_get`` / ``update_status`` / ``simulation_upsert`` /
``submission_receipt_get``, the registration metadata contract
(writes claim ``epic`` + declare side effects, reads claim ``None``),
and dispatcher-level claim verification for one write id and one read
id. Shared fixtures live in
:mod:`_epic_task_review_state_test_helpers`.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from yoke_core.domain import yoke_function_dispatch as dispatch_module
from yoke_core.domain import yoke_function_dispatch_claims as claims_module
from yoke_core.domain import yoke_function_dispatch_events as events_module
from yoke_core.domain.handlers import (
    workflow_item_epic_task_state as state_handlers,
)
from yoke_core.domain.handlers.__init_register__ import register_all_handlers
from yoke_core.domain.handlers._epic_task_review_state_test_helpers import (  # noqa: F401
    EPIC_ID,
    FAILING_RECEIPT,
    VALID_RECEIPT,
    db,
    db_with_task,
    handler_conns,
    make_request,
)
from yoke_core.domain.yoke_function_dispatch import dispatch
from yoke_core.domain.yoke_function_registry import (
    list_entries,
    reset_registry_for_tests,
)


class TestBodyGet:
    def test_returns_body_verbatim(self, handler_conns):
        outcome = state_handlers.handle_body_get(
            make_request("workflow_item.epic_task.body_get"),
        )
        assert outcome.primary_success
        assert outcome.result_payload["body"] == "task body line"

    def test_missing_task_is_target_not_found(self, handler_conns):
        outcome = state_handlers.handle_body_get(
            make_request("workflow_item.epic_task.body_get", task_num=99),
        )
        assert not outcome.primary_success
        assert outcome.error.code == "target_not_found"


class TestUpdateStatus:
    def test_valid_status_updates_row_and_syncs_label(self, handler_conns):
        with patch(
            "yoke_core.domain.epic.epic_task_sync.sync_task_label",
        ) as sync:
            outcome = state_handlers.handle_update_status(
                make_request(
                    "workflow_item.epic_task.update_status",
                    payload={"status": "implementing"},
                ),
            )
        assert outcome.primary_success
        assert outcome.result_payload["status"] == "implementing"
        sync.assert_called_once()
        row = handler_conns.execute(
            "SELECT status FROM epic_tasks WHERE epic_id = %s AND task_num = 1",
            (str(EPIC_ID),),
        ).fetchone()
        assert row["status"] == "implementing"

    def test_invalid_status_is_invalid_payload(self, handler_conns):
        outcome = state_handlers.handle_update_status(
            make_request(
                "workflow_item.epic_task.update_status",
                payload={"status": "not-a-status"},
            ),
        )
        assert not outcome.primary_success
        assert outcome.error.code == "invalid_payload"

    def test_terminal_status_is_pipeline_required(self, handler_conns):
        outcome = state_handlers.handle_update_status(
            make_request(
                "workflow_item.epic_task.update_status",
                payload={"status": "done"},
            ),
        )
        assert not outcome.primary_success
        assert outcome.error.code == "pipeline_required"
        assert "pipeline-owned" in outcome.error.message


class TestSimulationUpsert:
    def test_upsert_parses_clean_result(self, handler_conns):
        with patch(
            "yoke_core.domain.epic._qa_requirement_add_silent", return_value=23,
        ), patch("yoke_core.domain.epic._qa_run_add_silent") as add_run:
            outcome = state_handlers.handle_simulation_upsert(
                make_request(
                    "workflow_item.epic_task.simulation_upsert",
                    task_num=None,
                    payload={"phase": "plan", "body": "SIMULATION: CLEAN"},
                ),
            )
        assert outcome.primary_success
        assert outcome.result_payload["phase"] == "plan"
        assert f"{EPIC_ID}/plan" in outcome.result_payload["message"]
        assert add_run.call_args.kwargs["verdict"] == "pass"

    def test_missing_phase_is_invalid_payload(self, handler_conns):
        outcome = state_handlers.handle_simulation_upsert(
            make_request(
                "workflow_item.epic_task.simulation_upsert",
                task_num=None,
                payload={"body": "SIMULATION: CLEAN"},
            ),
        )
        assert not outcome.primary_success
        assert outcome.error.code == "invalid_payload"


class TestSubmissionReceiptGet:
    def _insert_note(self, conn, note_num: int, body: str) -> None:
        conn.execute(
            """INSERT INTO epic_progress_notes
               (epic_id, task_num, note_num, body, created_at)
               VALUES (%s, 1, %s, %s, '2026-01-01T00:00:00Z')""",
            (str(EPIC_ID), note_num, body),
        )
        conn.commit()

    def test_valid_receipt_returned(self, handler_conns):
        self._insert_note(handler_conns, 1, VALID_RECEIPT)
        outcome = state_handlers.handle_submission_receipt_get(
            make_request("workflow_item.epic_task.submission_receipt_get"),
        )
        assert outcome.primary_success
        assert outcome.result_payload["receipt"].startswith(f"PASS|{EPIC_ID}|1|1|")

    def test_no_receipt_is_target_not_found(self, handler_conns):
        outcome = state_handlers.handle_submission_receipt_get(
            make_request("workflow_item.epic_task.submission_receipt_get"),
        )
        assert not outcome.primary_success
        assert outcome.error.code == "target_not_found"

    def test_failing_receipt_is_receipt_invalid(self, handler_conns):
        self._insert_note(handler_conns, 1, FAILING_RECEIPT)
        outcome = state_handlers.handle_submission_receipt_get(
            make_request("workflow_item.epic_task.submission_receipt_get"),
        )
        assert not outcome.primary_success
        assert outcome.error.code == "receipt_invalid"

    def test_after_note_count_watermark_excludes_older_notes(self, handler_conns):
        self._insert_note(handler_conns, 1, VALID_RECEIPT)
        outcome = state_handlers.handle_submission_receipt_get(
            make_request(
                "workflow_item.epic_task.submission_receipt_get",
                payload={"after_note_count": 1},
            ),
        )
        assert not outcome.primary_success
        assert outcome.error.code == "target_not_found"


WRITE_IDS = (
    "workflow_item.epic_task.review_seed",
    "workflow_item.epic_task.review_insert",
    "workflow_item.epic_task.update_status",
    "workflow_item.epic_task.simulation_upsert",
)
READ_IDS = (
    "workflow_item.epic_task.review_get",
    "workflow_item.epic_task.review_list",
    "workflow_item.epic_task.body_get",
    "workflow_item.epic_task.submission_receipt_get",
)


class TestRegistrationShape:
    @pytest.fixture(autouse=True)
    def _registered(self):
        reset_registry_for_tests()
        register_all_handlers()
        yield
        reset_registry_for_tests()

    def test_writes_require_epic_claim_and_declare_side_effects(self):
        entries = {e.function_id: e for e in list_entries()}
        for fid in WRITE_IDS:
            assert fid in entries, f"{fid} not registered"
            assert entries[fid].claim_required_kind == "epic"
            assert entries[fid].side_effects, f"{fid} must declare side effects"

    def test_reads_need_no_claim_and_no_side_effects(self):
        entries = {e.function_id: e for e in list_entries()}
        for fid in READ_IDS:
            assert fid in entries, f"{fid} not registered"
            assert entries[fid].claim_required_kind is None
            assert entries[fid].side_effects == ()


class TestDispatcherClaimVerification:
    """Write ids deny without an epic work claim; reads pass without one."""

    @pytest.fixture(autouse=True)
    def _dispatch_env(self, monkeypatch):
        reset_registry_for_tests()
        register_all_handlers()
        monkeypatch.setenv("YOKE_SESSION_ID", "s-1")
        with patch.object(events_module, "emit_event"), patch.object(
            dispatch_module, "_idempotency_lookup", lambda *_a, **_k: None,
        ):
            yield
        reset_registry_for_tests()

    def test_update_status_denied_without_claim(self):
        with patch.object(
            claims_module, "who_claims_for_item", return_value=None,
        ):
            resp = dispatch(make_request(
                "workflow_item.epic_task.update_status",
                payload={"status": "implementing"},
            ))
        assert not resp.success
        assert resp.error.code == "claim_required"

    def test_review_insert_denied_on_session_mismatch(self):
        with patch.object(
            claims_module, "who_claims_for_item",
            return_value={"id": 1, "session_id": "OTHER"},
        ):
            resp = dispatch(make_request(
                "workflow_item.epic_task.review_insert",
                payload={"verdict": "pass", "body": "x"},
            ))
        assert not resp.success
        assert resp.error.code == "claim_required"

    def test_body_get_passes_without_claim(self, handler_conns):
        with patch.object(
            claims_module, "who_claims_for_item", return_value=None,
        ):
            resp = dispatch(make_request("workflow_item.epic_task.body_get"))
        assert resp.success
        assert resp.result["body"] == "task body line"
