"""Launch model knobs persist together and refuse unsupported combinations."""

from __future__ import annotations

import pytest

from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    assigned_launch,
    authorization,
    launch_connection,
)
from yoke_core.domain.session_launch_execution import (
    claim_assigned_launch,
    report_launch_attempt,
)
from yoke_core.domain.session_launch_requests import create_launch
from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError


def test_create_persists_model_effort_and_context_as_one_request() -> None:
    conn = launch_connection()
    add_relay(conn, surface="claude-cli", version="2.1.259")

    launch = create_launch(
        conn,
        auth=authorization(),
        request=LaunchRequest(
            project_id=10,
            executor_surface="claude-cli",
            instructions="Run the bounded task.",
            idempotency_key="all-model-knobs",
            model="claude-opus-4-8",
            reasoning_effort="max",
            context_window_tokens=1_000_000,
        ),
        now=NOW,
    ).launch

    assert launch.requested_model == "claude-opus-4-8"
    assert launch.requested_reasoning_effort == "max"
    assert launch.requested_context_window_tokens == 1_000_000


def test_create_persists_the_normalized_selection_sent_to_the_native() -> None:
    conn = launch_connection()
    add_relay(conn, surface="claude-cli", version="2.1.259")

    launch = create_launch(
        conn,
        auth=authorization(),
        request=LaunchRequest(
            project_id=10,
            executor_surface="claude-cli",
            instructions="Run the bounded task.",
            idempotency_key="normalized-model-knobs",
            model="  claude-opus-4-8  ",
            reasoning_effort=" MAX ",
        ),
        now=NOW,
    ).launch

    assert launch.requested_model == "claude-opus-4-8"
    assert launch.requested_reasoning_effort == "max"


def test_unsupported_context_refuses_with_harness_and_knob_code() -> None:
    conn = launch_connection()
    add_relay(conn, surface="codex-cli")

    with pytest.raises(SessionLaunchError) as raised:
        create_launch(
            conn,
            auth=authorization(),
            request=LaunchRequest(
                project_id=10,
                executor_surface="codex-cli",
                instructions="Run the bounded task.",
                idempotency_key="bad-context",
                model="gpt-5.6-sol",
                context_window_tokens=1_000_000,
            ),
            now=NOW,
        )

    assert raised.value.code == "codex_context_window_unsupported"


def test_named_provider_rejection_is_persisted_with_safe_detail() -> None:
    conn = launch_connection()
    add_relay(conn)
    launch = assigned_launch(conn, key="provider-rejection")
    claim = claim_assigned_launch(
        conn,
        launch_id=launch.launch_id,
        relay_id="relay-1",
        machine_id="machine-1",
        now=NOW,
    )

    failed = report_launch_attempt(
        conn,
        launch_id=launch.launch_id,
        lease_id=claim.lease_id,
        result_code="not_created",
        evidence={
            "result_code": "model_combo_unsupported",
            "probe_detail": "model does not support effort max",
        },
        now="2026-08-22T12:00:20Z",
    )

    assert failed.state == "failed"
    assert failed.result_code == "model_combo_unsupported"
    assert "model does not support effort max" in str(failed.result_evidence)
