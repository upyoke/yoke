"""Project a local launch secret into one authenticated hook field."""

from __future__ import annotations

import json

from yoke_harness.hooks.identity_stamp import record_then_stamp
from yoke_harness.session_launch_handoff import (
    LaunchProjection,
    launch_delivery_rendered,
    mark_launch_attestation_delivered,
    project_launch_attestation,
)


def stamp_hook_input(
    payload: dict,
    stdin_data: str,
    executor: str,
    event_name: str,
) -> tuple[str, LaunchProjection | None]:
    projection = project_launch_attestation(payload)
    stamped = record_then_stamp(payload, stdin_data, executor, event_name)
    if projection is not None:
        stamped = json.dumps(payload)
    return stamped, projection


def settle_projection(text: str, projection: LaunchProjection | None) -> None:
    if projection is not None and launch_delivery_rendered(text, projection):
        mark_launch_attestation_delivered(projection)


__all__ = ["settle_projection", "stamp_hook_input"]
