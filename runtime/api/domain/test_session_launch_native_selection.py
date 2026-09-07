"""Preview, create, retry, and relay delivery share native model validation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.domain.session_launch_test_support import (
    NOW,
    add_relay,
    authorization,
    launch_connection,
)
from runtime.api.domain.test_session_launch_handler_deadlines import (
    _request,
    _wire_handler,
)
from yoke_contracts.session_control.native_model_parsers import parse_cursor_models
from yoke_core.domain.handlers import session_launch as handlers
from yoke_core.domain.session_launch_requests import create_launch, retry_launch
from yoke_core.domain.session_launch_store import update_launch
from yoke_core.domain.session_launch_types import LaunchRequest, SessionLaunchError
from yoke_core.domain.session_relay_launch_lease import claim_next_launch
from yoke_core.domain.session_relay_types import RelayHeartbeat
from yoke_harness.session_relay_cursor_requests import cursor_model_selector
from yoke_harness.session_relay_runtime import RelayExecutionContext


SURFACE = "cursor-cli"
VERSION = "2026.08.25"
MODEL = "cursor-grok-4.6-high"


def _connection(*, preferred_models=None, preferred_efforts=None):
    conn = launch_connection()
    add_relay(
        conn,
        surface=SURFACE,
        version=VERSION,
        preferred_models=preferred_models,
        preferred_reasoning_efforts=preferred_efforts,
    )
    _observe(conn)
    return conn


def _observe(conn, model=MODEL):
    reading = {
        SURFACE: {
            "status": "ok",
            "source": "cursor-agent --list-models",
            "observed_at": NOW,
            "models": parse_cursor_models(
                f"{model} - Cursor Grok 4.6\n"
                "claude-opus-4-8-high - Claude Opus 4.8 1M\n"
            ),
        },
    }
    conn.execute(
        "UPDATE session_relays SET surface_native_models = ?", (json.dumps(reading),)
    )
    conn.commit()


def _create(conn, **selection):
    return create_launch(
        conn,
        auth=authorization(),
        now=NOW,
        request=LaunchRequest(
            project_id=10,
            executor_surface=SURFACE,
            instructions="Inspect current evidence.",
            idempotency_key="native-selection",
            **selection,
        ),
    ).launch


@pytest.mark.parametrize(
    ("model", "effort", "context", "code"),
    [
        (MODEL, "high", 1_000_000, "cursor_context_window_unsupported"),
        (MODEL, "medium", None, "cursor_reasoning_effort_conflict"),
        ("cursor-grok-4.6", "max", None, "cursor_model_unsupported"),
        (f"{MODEL}[effort=high]", None, None, "cursor_model_invalid"),
    ],
)
def test_preview_and_create_refuse_before_persisting_a_launch(
    monkeypatch, model, effort, context, code
):
    conn = _connection()
    _wire_handler(monkeypatch, conn)
    monkeypatch.setattr(handlers, "_fleet_policy", lambda *_args: False)
    selection = {
        "model": model,
        "reasoning_effort": effort,
        "context_window_tokens": context,
    }
    preview = handlers.handle_launch_preview(
        _request(
            "session_control.launch.preview",
            {"project": "launch-project", "executor_surface": SURFACE, **selection},
        )
    )
    assert not preview.primary_success
    assert preview.error.code == code
    with pytest.raises(SessionLaunchError) as raised:
        _create(conn, **selection)
    assert raised.value.code == code
    assert conn.execute("SELECT count(*) FROM session_launches").fetchone()[0] == 0


def test_preview_preserves_the_request_and_names_the_resolved_variant(monkeypatch):
    conn = _connection()
    _wire_handler(monkeypatch, conn)
    monkeypatch.setattr(handlers, "_fleet_policy", lambda *_args: False)
    preview = handlers.handle_launch_preview(
        _request(
            "session_control.launch.preview",
            {
                "project": "launch-project",
                "executor_surface": SURFACE,
                "model": "cursor-grok-4.6",
                "reasoning_effort": "high",
            },
        )
    )
    assert preview.primary_success, preview.error
    assert preview.result_payload["requested_model"] == "cursor-grok-4.6"
    assert preview.result_payload["model"] == MODEL
    assert preview.result_payload["context_window_tokens"] is None


def test_create_delivers_the_exact_native_selector_to_the_relay():
    conn = _connection()
    launch = _create(conn, model="cursor-grok-4.6", reasoning_effort="high")
    assert launch.requested_model == "cursor-grok-4.6"
    assert launch.resolved_model == MODEL
    jobs = claim_next_launch(
        conn,
        RelayHeartbeat(
            relay_id="relay-1",
            actor_id=1,
            machine_id="machine-1",
            hostname="relay-host",
            relay_version="source",
            surface_versions={SURFACE: VERSION},
            project_ids=(10,),
        ),
        now=NOW,
    )
    job = jobs[0]
    assert job.requested_model == MODEL
    assert job.requested_reasoning_effort == "high"
    assert job.requested_context_window_tokens is None
    context = RelayExecutionContext(
        job_kind="launch",
        job_id=launch.launch_id,
        lease_id="lease",
        surface=SURFACE,
        surface_version=VERSION,
        project_id=10,
        checkout=Path("/project"),
        native_instruction="Inspect current evidence.",
        launch_attestation="test-only",
        requested_model=job.requested_model,
        requested_reasoning_effort=job.requested_reasoning_effort,
        requested_context_window_tokens=job.requested_context_window_tokens,
    )
    assert cursor_model_selector(context) == MODEL


def test_retry_revalidates_against_the_current_machine_observation():
    conn = _connection()
    launch = _create(conn, model=MODEL)
    update_launch(conn, launch.launch_id, state="failed", result_code="native_failed")
    _observe(conn, model="cursor-grok-4.6-medium")
    with pytest.raises(SessionLaunchError) as raised:
        retry_launch(conn, launch_id=launch.launch_id, auth=authorization(), now=NOW)
    assert raised.value.code == "cursor_model_unsupported"


def test_configured_knobs_cannot_bypass_native_validation():
    conn = _connection(
        preferred_models={SURFACE: "cursor-grok-4.6[context=1m]"},
        preferred_efforts={SURFACE: "high"},
    )
    with pytest.raises(SessionLaunchError) as raised:
        _create(conn)
    assert raised.value.code == "cursor_context_window_unsupported"


def test_parameterized_preference_resolves_to_an_advertised_context_variant():
    conn = _connection(
        preferred_models={SURFACE: "claude-opus-4-8[context=1m,effort=high]"},
    )
    launch = _create(conn)
    assert launch.requested_context_window_tokens is None
    assert launch.resolved_model == "claude-opus-4-8-high"
    assert launch.resolved_context_window_tokens == 1_000_000
