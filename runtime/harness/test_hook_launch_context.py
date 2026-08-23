"""Client hook projection for relay-created session launches."""

from __future__ import annotations

import json

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
