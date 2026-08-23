"""Register the internal deployment member-item stamp write.

``deployment_item_stamp.record`` is the control-plane write the deploy
pipeline relays so ``deploy_stage`` and ``deployed_to`` land on the
addressed ``items.id`` over an https control plane as well as a local
Postgres connection. It is ``adapter_status='internal'`` (pipeline glue,
never an agent CLI surface), so it needs no CLI adapter row, and
``ambient_session_required=False`` because a deploy runner may resolve
no ambient harness session. It is claim-free because the pipeline holds
no session claim on member items by construction; the PROJECT +
items-write authorization scope is what gates the write.
"""

from __future__ import annotations

from yoke_core.domain.handlers import deployment_item_stamp as _stamp

_MODULE = "yoke_core.domain.handlers.deployment_item_stamp"


def register(registry) -> None:
    registry.register(
        "deployment_item_stamp.record",
        _stamp.handle_deployment_item_stamp,
        _stamp.DeploymentItemStampRequest,
        _stamp.DeploymentItemStampResponse,
        stability="stable",
        owner_module=_MODULE,
        target_kinds=["item"],
        side_effects=["item_deploy_stage_write", "item_deployed_to_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=["stampable_fields_only", "read_back_verified"],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
