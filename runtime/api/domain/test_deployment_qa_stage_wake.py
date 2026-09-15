"""Unit coverage for the QA wait notice message shapes and keys.

The recipient-resolution and message-insert wiring is covered for real
against a live connection in ``test_deployment_qa_stage_wake_delivery.py``;
this file stays to pure, conn-free message/key shape assertions.
"""

from __future__ import annotations

from yoke_core.domain.deployment_qa_stage_wake import (
    DRIVER,
    run_stage_wait_idempotency_key,
    run_stage_wait_message,
    stage_wait_idempotency_key,
    stage_wait_message,
)
from yoke_core.domain.merge_queue_landing_notice import HOLDER, STEERING


def test_item_key_is_stable_per_run_stage_and_item():
    key = stage_wait_idempotency_key("run-1", "item-qa", 42)

    assert key == stage_wait_idempotency_key("run-1", "item-qa", 42)
    assert key != stage_wait_idempotency_key("run-1", "item-qa", 43)
    assert key != stage_wait_idempotency_key("run-1", "other-stage", 42)
    assert key != stage_wait_idempotency_key("run-2", "item-qa", 42)


def test_run_key_is_stable_per_run_and_stage_and_distinct_from_any_item_key():
    key = run_stage_wait_idempotency_key("run-1", "run-qa")

    assert key == run_stage_wait_idempotency_key("run-1", "run-qa")
    assert key != run_stage_wait_idempotency_key("run-2", "run-qa")
    assert key != run_stage_wait_idempotency_key("run-1", "other-stage")
    assert key != stage_wait_idempotency_key("run-1", "run-qa", 42)


def test_item_message_names_the_run_stage_target_revision_item_and_reasons():
    body = stage_wait_message(
        run_id="run-1",
        stage_name="item-qa",
        item_ref="EXT-541",
        target_tier="persistent",
        revision="a" * 40,
        reasons="awaiting agent verdict",
        route=HOLDER,
    )

    assert "run-1" in body
    assert "item-qa" in body
    assert "EXT-541" in body
    assert "persistent" in body
    assert ("a" * 12) in body
    assert "awaiting agent verdict" in body
    assert "claim holder" in body


def test_item_message_names_steering_when_the_route_is_steering():
    body = stage_wait_message(
        run_id="run-1",
        stage_name="item-qa",
        item_ref="EXT-541",
        target_tier="",
        revision="",
        reasons="awaiting agent verdict",
        route=STEERING,
    )

    assert "steering seat" in body
    assert "claim holder is gone" in body


def test_run_message_names_the_run_stage_target_revision_and_reasons():
    body = run_stage_wait_message(
        run_id="run-9",
        stage_name="run-qa",
        target_tier="ephemeral",
        revision="b" * 40,
        reasons="awaiting agent verdict",
        route=DRIVER,
    )

    assert "run-9" in body
    assert "run-qa" in body
    assert "ephemeral" in body
    assert ("b" * 12) in body
    assert "awaiting agent verdict" in body
    assert "deploy-lock driver" in body


def test_run_message_names_steering_when_the_route_is_steering():
    body = run_stage_wait_message(
        run_id="run-9",
        stage_name="run-qa",
        target_tier="",
        revision="",
        reasons="awaiting agent verdict",
        route=STEERING,
    )

    assert "steering seat" in body
    assert "no session holds its deploy lock" in body
