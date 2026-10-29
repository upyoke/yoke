"""Launch-attestation projection and replay suppression."""

from __future__ import annotations

import json
import os
from pathlib import Path
import stat

from yoke_harness.session_launch_handoff import (
    HANDOFF_DIRECTORY_NAME,
    HANDOFF_TTL_SECONDS,
    LAUNCH_CONTEXT_ENV,
    launch_delivery_rendered,
    mark_launch_attestation_delivered,
    project_launch_attestation,
)


LAUNCH_ID = "11111111-1111-4111-8111-111111111111"
BINDING_ID = "22222222-2222-4222-8222-222222222222"
ATTESTATION = "single-use-secret"
RETRY_ATTESTATION = "retry-secret"


def _environ(attestation: str) -> dict[str, str]:
    return {
        LAUNCH_CONTEXT_ENV: json.dumps(
            {"launch_id": LAUNCH_ID, "attestation": attestation}
        )
    }


def test_environment_projects_until_rendered_delivery_is_proven(
    tmp_path: Path,
) -> None:
    payload: dict[str, object] = {"session_id": BINDING_ID}

    projection = project_launch_attestation(
        payload, environ=_environ(ATTESTATION), state_dir=tmp_path
    )

    assert projection is not None
    assert payload["yoke_launch"] == {
        "launch_id": LAUNCH_ID,
        "attestation": ATTESTATION,
    }
    assert ATTESTATION not in repr(projection)
    assert not launch_delivery_rendered("registration is still launching", projection)
    again = project_launch_attestation(
        {"session_id": BINDING_ID}, environ=_environ(ATTESTATION), state_dir=tmp_path
    )
    assert again == projection

    rendered = f"YOKE_SESSION_LAUNCH:{LAUNCH_ID}:message-id"
    assert launch_delivery_rendered(rendered, projection)
    mark_launch_attestation_delivered(projection, state_dir=tmp_path)
    markers = list((tmp_path / HANDOFF_DIRECTORY_NAME).glob("*.delivered"))
    assert [marker.name for marker in markers] == [
        f"{projection.attestation_digest}.delivered"
    ]
    assert stat.S_IMODE(markers[0].stat().st_mode) == 0o600
    assert (
        project_launch_attestation(
            {"session_id": BINDING_ID},
            environ=_environ(ATTESTATION),
            state_dir=tmp_path,
        )
        is None
    )


def test_environment_projection_binds_the_hook_session(tmp_path: Path) -> None:
    """The binding is the session the native turned out to be.

    An attestation carried in the environment says nothing about which session
    the native opened, so the binding has to come from the hook payload. While
    it did not, a launch reached through that channel wrote a durable process
    handle naming no session, and both termination by launch handle and the
    relay's process-death liveness went blind to that native.
    """
    payload: dict[str, object] = {
        "session_id": BINDING_ID,
        "yoke_launch": {"launch_id": LAUNCH_ID, "attestation": "forged"},
    }

    projection = project_launch_attestation(
        payload, environ=_environ(ATTESTATION), state_dir=tmp_path
    )

    assert projection is not None
    assert projection.binding_id == BINDING_ID
    assert payload["yoke_launch"]["attestation"] == ATTESTATION
    untrusted: dict[str, object] = {"yoke_launch": {"launch_id": LAUNCH_ID}}
    assert project_launch_attestation(untrusted, environ={}, state_dir=tmp_path) is None
    assert "yoke_launch" not in untrusted


def test_retry_projects_its_new_attestation_after_earlier_delivery(
    tmp_path: Path,
) -> None:
    first = project_launch_attestation(
        {"session_id": BINDING_ID}, environ=_environ(ATTESTATION), state_dir=tmp_path
    )
    assert first is not None
    mark_launch_attestation_delivered(first, state_dir=tmp_path)

    payload: dict[str, object] = {"session_id": BINDING_ID}
    retry = project_launch_attestation(
        payload, environ=_environ(RETRY_ATTESTATION), state_dir=tmp_path
    )

    assert retry is not None
    assert retry.launch_id == LAUNCH_ID
    assert retry.attestation_digest != first.attestation_digest
    assert payload["yoke_launch"] == {
        "launch_id": LAUNCH_ID,
        "attestation": RETRY_ATTESTATION,
    }
    assert (
        project_launch_attestation(
            {"session_id": BINDING_ID},
            environ=_environ(ATTESTATION),
            state_dir=tmp_path,
        )
        is None
    )


def test_writing_a_marker_prunes_markers_older_than_the_ttl(tmp_path: Path) -> None:
    directory = tmp_path / HANDOFF_DIRECTORY_NAME
    directory.mkdir(mode=0o700)
    expired = directory / f"{'0' * 64}.delivered"
    expired.write_text("{}")
    stale_time = expired.stat().st_mtime - HANDOFF_TTL_SECONDS - 60
    os.utime(expired, (stale_time, stale_time))
    projection = project_launch_attestation(
        {"session_id": BINDING_ID}, environ=_environ(ATTESTATION), state_dir=tmp_path
    )
    assert projection is not None

    mark_launch_attestation_delivered(projection, state_dir=tmp_path)

    assert sorted(path.name for path in directory.iterdir()) == [
        f"{projection.attestation_digest}.delivered"
    ]
