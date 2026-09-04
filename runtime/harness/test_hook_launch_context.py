"""Client hook projection for relay-created session launches."""

from __future__ import annotations

import json
import os

from yoke_harness import session_launch_handoff
from yoke_harness.hooks import launch_context
from yoke_harness.session_launch_handoff import LAUNCH_CONTEXT_ENV


LAUNCH_ID = "11111111-1111-4111-8111-111111111111"
SESSION_ID = "22222222-2222-4222-8222-222222222222"
ATTESTATION = "single-use-secret"


def test_hook_input_projects_environment_context_after_identity_stamp(
    monkeypatch,
) -> None:
    monkeypatch.setenv(
        LAUNCH_CONTEXT_ENV,
        json.dumps({"launch_id": LAUNCH_ID, "attestation": ATTESTATION}),
    )
    monkeypatch.setattr(
        launch_context,
        "record_then_stamp",
        lambda payload, stdin, executor, event: stdin,
    )
    payload: dict[str, object] = {"session_id": SESSION_ID}

    stamped, projection = launch_context.stamp_hook_input(
        payload,
        json.dumps(payload),
        "codex-cli",
        "SessionStart",
    )

    assert projection is not None
    assert json.loads(stamped)["yoke_launch"] == {
        "launch_id": LAUNCH_ID,
        "attestation": ATTESTATION,
    }


def test_projection_settles_only_when_launch_delivery_token_survives(
    monkeypatch,
) -> None:
    projection = launch_context.LaunchProjection(LAUNCH_ID)
    settled = []
    monkeypatch.setattr(
        launch_context,
        "mark_launch_attestation_delivered",
        settled.append,
    )

    launch_context.settle_projection("launch is still starting", projection)
    launch_context.settle_projection(
        f"YOKE_SESSION_LAUNCH:{LAUNCH_ID}:message-id",
        projection,
    )

    assert settled == [projection]


def test_claude_session_start_delivery_writes_replay_marker(
    monkeypatch,
    tmp_path,
) -> None:
    launch_environment = json.dumps(
        {"launch_id": LAUNCH_ID, "attestation": ATTESTATION}
    )
    monkeypatch.setenv(LAUNCH_CONTEXT_ENV, launch_environment)
    monkeypatch.setattr(
        session_launch_handoff.machine_config, "cache_dir", lambda: tmp_path
    )
    monkeypatch.setattr(
        launch_context,
        "record_then_stamp",
        lambda payload, stdin, executor, event: stdin,
    )
    payload: dict[str, object] = {"session_id": SESSION_ID}

    _, projection = launch_context.stamp_hook_input(
        payload,
        json.dumps(payload),
        "claude-cli",
        "SessionStart",
    )
    assert projection is not None

    launch_context.settle_projection(
        f"YOKE_SESSION_LAUNCH:{LAUNCH_ID}:message-id",
        projection,
    )

    marker = (
        tmp_path
        / session_launch_handoff.HANDOFF_DIRECTORY_NAME
        / f"{LAUNCH_ID}.delivered"
    )
    assert marker.is_file()
    assert (
        session_launch_handoff.project_launch_attestation(
            {"session_id": SESSION_ID},
            environ={LAUNCH_CONTEXT_ENV: launch_environment},
        )
        is None
    )

    os.utime(marker, (0, 0))
    _, replayed = launch_context.stamp_hook_input(
        {"session_id": SESSION_ID},
        json.dumps({"session_id": SESSION_ID}),
        "claude-cli",
        "SessionStart",
    )

    assert replayed == projection
