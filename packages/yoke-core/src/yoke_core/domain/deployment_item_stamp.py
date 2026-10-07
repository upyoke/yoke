"""Typed caller for deployment member-item stamps and the release flip.

The deploy pipeline retains complete public item refs throughout its call
chain. Stamps go through ``deployment_item_stamp.record``; the release flip
uses ``done_transition.item_status_set`` with a request-scoped claim bypass.
Both refuse anything but a verified write.
"""

from __future__ import annotations

from yoke_core.domain.public_item_target import public_item_target

from typing import Any, Mapping

from yoke_core.api.service_client_structured_api_adapter import call_dispatcher


STAMP_FUNCTION_ID = "deployment_item_stamp.record"
RELEASE_STATUS_FUNCTION_ID = "done_transition.item_status_set"


class DeploymentItemStampError(RuntimeError):
    """A member-item stamp or release flip did not land on the addressed row."""


def stamp_item_field(item_id: int | str, field: str, value: str) -> dict[str, Any]:
    """Stamp one scalar on the named item and refuse unless the row verifies."""
    resp = call_dispatcher(
        function_id=STAMP_FUNCTION_ID,
        target=public_item_target(item_id),
        payload={"field": field, "value": value},
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise DeploymentItemStampError(
            f"stamp {field}={value!r} on {item_id} failed: {message}"
        )
    data: Mapping[str, Any] = resp.result or {}
    if not data.get("verified"):
        raise DeploymentItemStampError(
            f"stamp {field}={value!r} on {item_id} was not verified"
        )
    return dict(data)


def transition_member_to_release(item_id: int | str, run_id: str) -> None:
    """Flip ``implemented`` → ``release`` with a request-scoped claim bypass."""
    resp = call_dispatcher(
        function_id=RELEASE_STATUS_FUNCTION_ID,
        target=public_item_target(item_id),
        payload={
            "field": "status",
            "value": "release",
            "claim_bypass": f"deploy-pipeline:run-{run_id}",
            "status_source": "deploy_pipeline",
            "no_github": True,
            "rebuild_board": False,
        },
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise DeploymentItemStampError(f"status=release on {item_id} failed: {message}")
    data: Mapping[str, Any] = resp.result or {}
    if not data.get("status_write_success"):
        err = data.get("status_write_error") or "status write refused"
        raise DeploymentItemStampError(
            f"status=release on {item_id} did not apply: {err}"
        )


__all__ = [
    "DeploymentItemStampError",
    "RELEASE_STATUS_FUNCTION_ID",
    "STAMP_FUNCTION_ID",
    "stamp_item_field",
    "transition_member_to_release",
]
