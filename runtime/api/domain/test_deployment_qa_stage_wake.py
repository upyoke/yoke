"""Unit coverage for the item-scoped QA wait notice primitives."""

from __future__ import annotations

from unittest import mock

from yoke_core.domain import deployment_qa_stage_wake as wake_mod
from yoke_core.domain.deployment_qa_stage_wake import (
    notify_item_scoped_qa_wait,
    stage_wait_idempotency_key,
    stage_wait_message,
)


def test_idempotency_key_is_stable_per_run_stage_and_item():
    key = stage_wait_idempotency_key("run-1", "item-qa", 42)

    assert key == stage_wait_idempotency_key("run-1", "item-qa", 42)
    assert key != stage_wait_idempotency_key("run-1", "item-qa", 43)
    assert key != stage_wait_idempotency_key("run-1", "other-stage", 42)
    assert key != stage_wait_idempotency_key("run-2", "item-qa", 42)


def test_message_names_the_run_stage_and_reasons():
    body = stage_wait_message(
        run_id="run-1", stage_name="item-qa", reasons="awaiting agent verdict"
    )

    assert "run-1" in body
    assert "item-qa" in body
    assert "awaiting agent verdict" in body


def test_notify_delegates_to_push_notice_with_the_stable_key():
    with mock.patch.object(
        wake_mod, "push_notice", return_value="delivered"
    ) as push:
        result = notify_item_scoped_qa_wait(
            conn=object(),
            run_id="run-1",
            stage_name="item-qa",
            item_id=42,
            project_id=7,
            reasons="awaiting agent verdict",
        )

    assert result == "delivered"
    push.assert_called_once()
    kwargs = push.call_args.kwargs
    assert kwargs["item_id"] == 42
    assert kwargs["project_id"] == 7
    assert kwargs["idempotency_key"] == stage_wait_idempotency_key(
        "run-1", "item-qa", 42
    )
    body = kwargs["body_for_route"]("holder")
    assert "run-1" in body and "item-qa" in body
