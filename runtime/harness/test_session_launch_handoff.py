"""Owner-only launch-attestation projection and replay suppression."""

from __future__ import annotations

import json
from pathlib import Path
import stat

from yoke_harness.session_launch_handoff import (
    HANDOFF_DIRECTORY_NAME,
    LAUNCH_CONTEXT_ENV,
    launch_delivery_rendered,
    mark_launch_attestation_delivered,
    project_launch_attestation,
    stage_launch_attestation,
)


LAUNCH_ID = "11111111-1111-4111-8111-111111111111"
BINDING_ID = "22222222-2222-4222-8222-222222222222"
ATTESTATION = "single-use-secret"


def test_sidecar_projects_until_rendered_delivery_is_proven(tmp_path: Path) -> None:
    assert stage_launch_attestation(
        LAUNCH_ID,
        ATTESTATION,
        binding_id=BINDING_ID,
        state_dir=tmp_path,
    )
    payload: dict[str, object] = {"session_id": BINDING_ID}

    projection = project_launch_attestation(
        payload,
        environ={},
        state_dir=tmp_path,
    )

    assert projection is not None
    assert payload["yoke_launch"] == {
        "launch_id": LAUNCH_ID,
        "attestation": ATTESTATION,
    }
    assert ATTESTATION not in repr(projection)
    assert not launch_delivery_rendered("registration is still launching", projection)
    retry = project_launch_attestation(
        {"session_id": BINDING_ID}, environ={}, state_dir=tmp_path
    )
    assert retry == projection

    rendered = f"YOKE_SESSION_LAUNCH:{LAUNCH_ID}:message-id"
    assert launch_delivery_rendered(rendered, projection)
    mark_launch_attestation_delivered(projection, state_dir=tmp_path)
    assert (
        project_launch_attestation(
            {"session_id": BINDING_ID}, environ={}, state_dir=tmp_path
        )
        is None
    )


def test_handoff_files_are_owner_only_and_untrusted_payload_is_removed(
    tmp_path: Path,
) -> None:
    assert stage_launch_attestation(LAUNCH_ID, ATTESTATION, state_dir=tmp_path)
    files = list((tmp_path / HANDOFF_DIRECTORY_NAME).glob("*.json"))
    assert len(files) == 1
    assert stat.S_IMODE(files[0].stat().st_mode) == 0o600
    payload: dict[str, object] = {
        "session_id": "not-a-uuid",
        "yoke_launch": {"launch_id": LAUNCH_ID, "attestation": ATTESTATION},
    }

    assert project_launch_attestation(payload, environ={}, state_dir=tmp_path) is None
    assert "yoke_launch" not in payload


def test_environment_projection_uses_the_same_replay_marker(tmp_path: Path) -> None:
    """The binding is the session the native turned out to be, either way.

    An attestation carried in the environment says nothing about which session
    the native opened, so the binding has to come from the hook payload. While
    it did not, a launch reached through that channel wrote a durable process
    handle naming no session, and both termination by launch handle and the
    relay's process-death liveness went blind to that native.
    """
    environ = {
        LAUNCH_CONTEXT_ENV: json.dumps(
            {"launch_id": LAUNCH_ID, "attestation": ATTESTATION}
        )
    }
    payload: dict[str, object] = {"session_id": BINDING_ID}

    projection = project_launch_attestation(
        payload,
        environ=environ,
        state_dir=tmp_path,
    )

    assert projection is not None
    assert projection.binding_id == BINDING_ID
    mark_launch_attestation_delivered(projection, state_dir=tmp_path)
    assert (
        project_launch_attestation(
            {"session_id": BINDING_ID},
            environ=environ,
            state_dir=tmp_path,
        )
        is None
    )
