"""A launch resolves the knobs it names; every unnamed knob is the vendor's."""

from __future__ import annotations

import json

from yoke_core.domain.session_launch_machine_models import (
    EXPLICIT_SOURCE,
    VENDOR_DEFAULT_SOURCE,
    resolve_machine_selection,
)
from yoke_core.domain.session_launch_requests import create_launch, retry_launch
from yoke_core.domain.session_launch_store import update_launch
from yoke_core.domain.session_launch_types import LaunchRequest

from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    authorization,
    launch_connection,
    plan_limit_document,
)


SURFACE = "codex-cli"
NEAR_RESET = "2026-08-22T13:00:00Z"


def _machine(conn, machine_id: str, *, remaining: float) -> None:
    add_relay(
        conn,
        relay_id=f"relay-{machine_id}",
        machine_id=machine_id,
        surface=SURFACE,
        plan_limits=plan_limit_document(
            SURFACE, remaining_percent=remaining, resets_at=NEAR_RESET
        ),
    )


def _create(
    conn,
    *,
    key: str,
    model: str | None = None,
    reasoning_effort: str | None = None,
):
    return create_launch(
        conn,
        auth=authorization(actor_id=1),
        request=LaunchRequest(
            project_id=10,
            executor_surface=SURFACE,
            instructions="Report the current evidence.",
            idempotency_key=key,
            model=model,
            reasoning_effort=reasoning_effort,
        ),
        now=NOW,
    )


def test_an_unnamed_model_launches_on_the_vendor_default() -> None:
    conn = launch_connection()
    _machine(conn, "machine-roomy", remaining=90.0)
    _machine(conn, "machine-tight", remaining=10.0)

    launch = _create(conn, key="vendor-default").launch

    assert launch.assigned_machine_id == "machine-roomy"
    assert launch.requested_model is None
    assert launch.resolved_model is None
    assert launch.resolved_reasoning_effort is None


def test_an_explicit_model_and_effort_are_launched_as_named() -> None:
    conn = launch_connection()
    _machine(conn, "machine-roomy", remaining=90.0)

    launch = _create(
        conn, key="explicit-model", model="gpt-5.4", reasoning_effort="high"
    ).launch

    assert launch.requested_model == "gpt-5.4"
    assert launch.resolved_model == "gpt-5.4"
    assert launch.requested_reasoning_effort == "high"
    assert launch.resolved_reasoning_effort == "high"


def test_each_knob_names_whether_it_was_requested_or_vendor_default() -> None:
    conn = launch_connection()
    add_relay(conn, relay_id="relay-a", machine_id="machine-a", surface=SURFACE)

    resolved = resolve_machine_selection(
        conn,
        requested_model="gpt-5.4",
        requested_reasoning_effort=None,
        requested_context_window_tokens=None,
        machine_id="machine-a",
        surface=SURFACE,
    )

    assert resolved.model == "gpt-5.4"
    assert resolved.sources["model"] == EXPLICIT_SOURCE
    assert resolved.sources["reasoning_effort"] == VENDOR_DEFAULT_SOURCE
    assert resolved.sources["context_window_tokens"] == VENDOR_DEFAULT_SOURCE


def test_a_level_launch_attributes_its_knobs_to_the_level_option() -> None:
    conn = launch_connection()
    add_relay(conn, relay_id="relay-a", machine_id="machine-a", surface=SURFACE)

    resolved = resolve_machine_selection(
        conn,
        requested_model="gpt-5.4",
        requested_reasoning_effort="high",
        requested_context_window_tokens=None,
        machine_id="machine-a",
        surface=SURFACE,
        explicit_source="level SENIOR option",
    )

    assert resolved.to_dict()["model_source"] == "level SENIOR option"
    assert resolved.to_dict()["reasoning_effort_source"] == "level SENIOR option"
    assert resolved.to_dict()["context_window_source"] == VENDOR_DEFAULT_SOURCE


def test_blank_knobs_count_as_unnamed() -> None:
    conn = launch_connection()
    add_relay(conn, relay_id="relay-a", machine_id="machine-a", surface=SURFACE)

    resolved = resolve_machine_selection(
        conn,
        requested_model="   ",
        requested_reasoning_effort="",
        requested_context_window_tokens=None,
        machine_id="machine-a",
        surface=SURFACE,
    )

    assert resolved.model is None
    assert resolved.reasoning_effort is None
    assert resolved.sources["model"] == VENDOR_DEFAULT_SOURCE


def test_a_replay_of_the_same_request_is_still_the_same_request() -> None:
    conn = launch_connection()
    _machine(conn, "machine-roomy", remaining=90.0)
    _machine(conn, "machine-tight", remaining=10.0)
    first = _create(conn, key="replay-key", model="gpt-5.4")
    # The roomy machine burns down between the create and its replay, so the
    # replay would place elsewhere if it were a new request.
    conn.execute(
        "UPDATE session_relays SET surface_plan_limits = ? WHERE machine_id = ?",
        (
            json.dumps(
                plan_limit_document(
                    SURFACE, remaining_percent=1.0, resets_at=NEAR_RESET
                )
            ),
            "machine-roomy",
        ),
    )
    conn.commit()

    replay = _create(conn, key="replay-key", model="gpt-5.4")

    assert replay.deduplicated is True
    assert replay.launch.launch_id == first.launch.launch_id
    assert replay.launch.assigned_machine_id == "machine-roomy"


def test_a_retried_launch_keeps_its_named_selection_on_a_new_machine() -> None:
    conn = launch_connection()
    _machine(conn, "machine-roomy", remaining=90.0)
    launch = _create(
        conn, key="retry-key", model="gpt-5.4", reasoning_effort="xhigh"
    ).launch
    update_launch(conn, launch.launch_id, state="failed", result_code="native_failed")
    conn.execute("DELETE FROM session_relays WHERE machine_id = 'machine-roomy'")
    _machine(conn, "machine-other", remaining=50.0)

    retried = retry_launch(
        conn,
        launch_id=launch.launch_id,
        auth=authorization(actor_id=1),
        now=NOW,
    )

    assert retried.assigned_machine_id == "machine-other"
    assert retried.resolved_model == "gpt-5.4"
    assert retried.resolved_reasoning_effort == "xhigh"
