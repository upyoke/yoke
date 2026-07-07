"""Tests for the ``workflow_item.epic_task.review_*`` handler family.

Direct handler-call coverage against a disposable test DB; qa-bridge
writes are patched at the canonical ``yoke_core.domain.epic`` patch
targets (mirroring ``runtime/api/test_epic_review.py``). Shared
fixtures live in :mod:`_epic_task_review_state_test_helpers`.
"""

from __future__ import annotations

from unittest.mock import patch

from yoke_core.domain.handlers import (
    workflow_item_epic_task_review as review_handlers,
)
from yoke_core.domain.handlers._epic_task_review_state_test_helpers import (  # noqa: F401
    EPIC_ID,
    db,
    db_with_task,
    handler_conns,
    insert_review_row,
    make_request,
)


class TestReviewSeed:
    def test_seed_creates_requirement(self, handler_conns):
        with patch(
            "yoke_core.domain.epic._qa_requirement_add_silent", return_value=17,
        ):
            outcome = review_handlers.handle_review_seed(
                make_request("workflow_item.epic_task.review_seed"),
            )
        assert outcome.primary_success
        assert outcome.result_payload["epic_id"] == EPIC_ID
        assert outcome.result_payload["task_num"] == 1
        assert "req_id=17" in outcome.result_payload["message"]

    def test_seed_missing_task_is_target_not_found(self, handler_conns):
        outcome = review_handlers.handle_review_seed(
            make_request("workflow_item.epic_task.review_seed", task_num=99),
        )
        assert not outcome.primary_success
        assert outcome.error.code == "target_not_found"

    def test_missing_task_num_is_invalid_payload(self, handler_conns):
        outcome = review_handlers.handle_review_seed(
            make_request("workflow_item.epic_task.review_seed", task_num=None),
        )
        assert not outcome.primary_success
        assert outcome.error.code == "invalid_payload"


class TestReviewInsert:
    def test_insert_normalizes_uppercase_verdict(self, handler_conns):
        with patch(
            "yoke_core.domain.epic._ensure_implementation_review_requirement",
            return_value=7,
        ), patch("yoke_core.domain.epic._qa_run_add_silent") as add_run:
            outcome = review_handlers.handle_review_insert(
                make_request(
                    "workflow_item.epic_task.review_insert",
                    payload={"verdict": "PASS", "body": "Looks good"},
                ),
            )
        assert outcome.primary_success
        assert outcome.result_payload["verdict"] == "pass"
        assert add_run.call_args.kwargs["verdict"] == "pass"

    def test_insert_invalid_verdict_rejected(self, handler_conns):
        outcome = review_handlers.handle_review_insert(
            make_request(
                "workflow_item.epic_task.review_insert",
                payload={"verdict": "maybe", "body": "x"},
            ),
        )
        assert not outcome.primary_success
        assert outcome.error.code == "invalid_payload"


class TestReviewGet:
    def test_get_reads_latest_review(self, handler_conns):
        insert_review_row(
            handler_conns, 1001, "pass", "Good work", "2026-01-02T00:00:00Z",
        )
        outcome = review_handlers.handle_review_get(
            make_request("workflow_item.epic_task.review_get"),
        )
        assert outcome.primary_success
        parts = outcome.result_payload["review"].split("|")
        assert parts[3] == "PASS"
        assert "Good work" in parts[4]

    def test_get_without_review_is_target_not_found(self, handler_conns):
        outcome = review_handlers.handle_review_get(
            make_request("workflow_item.epic_task.review_get"),
        )
        assert not outcome.primary_success
        assert outcome.error.code == "target_not_found"


class TestReviewList:
    def test_list_empty_is_success_with_zero_count(self, handler_conns):
        outcome = review_handlers.handle_review_list(
            make_request("workflow_item.epic_task.review_list"),
        )
        assert outcome.primary_success
        assert outcome.result_payload["count"] == 0
        assert outcome.result_payload["reviews"] == ""

    def test_list_returns_newest_first_and_honors_limit(self, handler_conns):
        insert_review_row(
            handler_conns, 1001, "fail", "first attempt", "2026-01-01T00:00:00Z",
        )
        insert_review_row(
            handler_conns, 1001, "pass", "second attempt", "2026-01-02T00:00:00Z",
        )
        outcome = review_handlers.handle_review_list(
            make_request("workflow_item.epic_task.review_list"),
        )
        assert outcome.primary_success
        assert outcome.result_payload["count"] == 2
        first_line = outcome.result_payload["reviews"].splitlines()[0]
        assert "second attempt" in first_line

        limited = review_handlers.handle_review_list(
            make_request(
                "workflow_item.epic_task.review_list", payload={"limit": 1},
            ),
        )
        assert limited.result_payload["count"] == 1

    def test_count_is_row_count_not_line_count(self, handler_conns):
        # JSON-escaped \n: the extracted review body spans three lines.
        insert_review_row(
            handler_conns, 1001, "pass",
            "# Report\\nline two\\nline three", "2026-01-01T00:00:00Z",
        )
        outcome = review_handlers.handle_review_list(
            make_request("workflow_item.epic_task.review_list"),
        )
        assert outcome.primary_success
        assert "\n" in outcome.result_payload["reviews"]
        assert outcome.result_payload["count"] == 1
