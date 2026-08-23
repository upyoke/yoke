"""Typed caller for deployment member-item stamps and the release flip.

The deploy pipeline addresses member items by internal ``items.id``. A
string digit crossing a CLI/router boundary is a *public sequence*
under the default project, not that id — so this module never stringifies
an id into an item-ref argument. Stamps go through
``deployment_item_stamp.record``; the implemented→release flip goes
through ``done_transition.item_status_set`` (request-scoped claim bypass,
not a process-global environment variable). Both raise on anything but
a verified write so a silent miss cannot look like success.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher


STAMP_FUNCTION_ID = "deployment_item_stamp.record"
RELEASE_STATUS_FUNCTION_ID = "done_transition.item_status_set"


class DeploymentItemStampError(RuntimeError):
    """A member-item stamp or release flip did not land on the addressed row."""


def stamp_item_field(item_id: int, field: str, value: str) -> dict[str, Any]:
    """Stamp one scalar on ``items.id`` and refuse unless the row verifies."""
    resp = call_dispatcher(
        function_id=STAMP_FUNCTION_ID,
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={"field": field, "value": value},
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise DeploymentItemStampError(
            f"stamp {field}={value!r} on items.id={item_id} failed: {message}"
        )
    data: Mapping[str, Any] = resp.result or {}
    if not data.get("verified"):
        raise DeploymentItemStampError(
            f"stamp {field}={value!r} on items.id={item_id} was not verified"
        )
    return dict(data)


def transition_member_to_release(item_id: int, run_id: str) -> None:
    """Flip ``implemented`` → ``release`` with a request-scoped claim bypass."""
    resp = call_dispatcher(
        function_id=RELEASE_STATUS_FUNCTION_ID,
        target=TargetRef(kind="item", item_id=int(item_id)),
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
        raise DeploymentItemStampError(
            f"status=release on items.id={item_id} failed: {message}"
        )
    data: Mapping[str, Any] = resp.result or {}
    if not data.get("status_write_success"):
        err = data.get("status_write_error") or "status write refused"
        raise DeploymentItemStampError(
            f"status=release on items.id={item_id} did not apply: {err}"
        )


__all__ = [
    "DeploymentItemStampError",
    "RELEASE_STATUS_FUNCTION_ID",
    "STAMP_FUNCTION_ID",
    "stamp_item_field",
    "transition_member_to_release",
]
