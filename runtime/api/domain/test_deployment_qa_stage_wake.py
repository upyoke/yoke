"""Unit coverage for the QA wait notice message shapes and keys.

The recipient-resolution and message-insert wiring is covered for real
against a live connection in ``test_deployment_qa_stage_wake_delivery.py``;
this file stays to pure, conn-free message/key shape assertions.
"""

from __future__ import annotations

from yoke_core.domain.deployment_qa_stage_wake import (
    run_stage_wait_idempotency_key,
    run_stage_wait_message,
    stage_wait_idempotency_key,
    stage_wait_message,
)
from yoke_core.domain.deployment_run_driver_notice import DRIVER
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
        names_cases=False,
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
        names_cases=False,
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
        names_cases=False,
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
        names_cases=False,
    )

    assert "steering seat" in body
    assert "no session holds its deploy lock" in body


def test_item_message_names_the_stage_and_member_bound_invocation():
    body = stage_wait_message(
        run_id="run-1",
        stage_name="item-qa",
        item_ref="EXT-541",
        target_tier="persistent",
        revision="a" * 40,
        reasons="awaiting agent verdict",
        route=HOLDER,
        names_cases=False,
    )

    assert (
        "yoke qa plan run --deployment-run-id run-1 --stage item-qa "
        "--member EXT-541 --plan PLAN --project PROJECT" in body
    )
    assert "never counts" in body


def test_run_message_names_the_stage_bound_invocation_without_a_member():
    body = run_stage_wait_message(
        run_id="run-9",
        stage_name="run-qa",
        target_tier="ephemeral",
        revision="b" * 40,
        reasons="awaiting agent verdict",
        route=DRIVER,
        names_cases=False,
    )

    assert (
        "yoke qa plan run --deployment-run-id run-9 --stage run-qa "
        "--plan PLAN --project PROJECT" in body
    )
    assert "--member" not in body


def test_a_stage_that_already_names_cases_gets_a_recipe_without_a_plan():
    body = stage_wait_message(
        run_id="run-1",
        stage_name="item-qa",
        item_ref="EXT-541",
        target_tier="persistent",
        revision="a" * 40,
        reasons="awaiting agent verdict",
        route=HOLDER,
        names_cases=True,
    )

    assert (
        "yoke qa plan run --deployment-run-id run-1 --stage item-qa "
        "--member EXT-541 --project PROJECT" in body
    )
    assert "--plan" not in body


def test_a_run_scoped_stage_that_already_names_cases_omits_the_plan_too():
    body = run_stage_wait_message(
        run_id="run-9",
        stage_name="run-qa",
        target_tier="ephemeral",
        revision="b" * 40,
        reasons="awaiting agent verdict",
        route=DRIVER,
        names_cases=True,
    )

    assert (
        "yoke qa plan run --deployment-run-id run-9 --stage run-qa "
        "--project PROJECT" in body
    )
    assert "--plan" not in body
    assert "--member" not in body


def test_item_message_for_a_discharged_member_does_not_hand_plan_run():
    statement = (
        "This member's stage is already satisfied: requirement #17 "
        "records post_deploy_no_obligation, which discharges the stage "
        "without cases. Steering re-drives the run and the stage gate "
        "reads that discharge. Do not run anything else; there is "
        "nothing for this member to run."
    )
    body = stage_wait_message(
        run_id="run-1",
        stage_name="item-qa",
        item_ref="EXT-541",
        target_tier="persistent",
        revision="a" * 40,
        reasons="no completed scoped QA execution exists",
        route=HOLDER,
        names_cases=False,
        discharge=statement,
    )

    assert statement in body
    assert "yoke qa plan run" not in body
    assert "still needs to" not in body
