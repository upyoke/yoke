"""Register the internal done-transition control-plane reads.

These ``done_transition.*`` functions are pure control-plane reads the
transport-aware done-transition engine relays to so its context load,
single-field reads, blocked-flag / preconditions / deployment guards, and
post-done epic cascade reads run over an https control plane as well as a
local Postgres connection. They are ``adapter_status='internal'`` (engine
glue, never an agent CLI surface), so they need no CLI adapter row.
"""

from __future__ import annotations

from yoke_core.domain.handlers import done_transition_deploy_reads as _dep
from yoke_core.domain.handlers import done_transition_item_reads as _item

_ITEM_MODULE = "yoke_core.domain.handlers.done_transition_item_reads"
_DEPLOY_MODULE = "yoke_core.domain.handlers.done_transition_deploy_reads"


def _register_read(
    registry,
    function_id,
    handler,
    request_model,
    response_model,
    *,
    owner_module,
    target_kinds,
) -> None:
    registry.register(
        function_id,
        handler,
        request_model,
        response_model,
        stability="stable",
        owner_module=owner_module,
        target_kinds=target_kinds,
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
    )


def register(registry) -> None:
    _register_read(
        registry,
        "done_transition.item_context",
        _item.handle_item_context,
        _item.ItemContextRequest,
        _item.ItemContextResponse,
        owner_module=_ITEM_MODULE,
        target_kinds=["item"],
    )
    _register_read(
        registry,
        "done_transition.item_field",
        _item.handle_item_field,
        _item.ItemFieldRequest,
        _item.ItemFieldResponse,
        owner_module=_ITEM_MODULE,
        target_kinds=["item"],
    )
    _register_read(
        registry,
        "done_transition.blocked_gate",
        _item.handle_blocked_gate,
        _item.BlockedGateRequest,
        _item.BlockedGateResponse,
        owner_module=_ITEM_MODULE,
        target_kinds=["item"],
    )
    _register_read(
        registry,
        "done_transition.epic_task_list",
        _item.handle_epic_task_list,
        _item.EpicTaskListRequest,
        _item.EpicTaskListResponse,
        owner_module=_ITEM_MODULE,
        target_kinds=["global"],
    )
    _register_read(
        registry,
        "done_transition.epic_task_github_issues",
        _item.handle_epic_task_github_issues,
        _item.EpicTaskGithubIssuesRequest,
        _item.EpicTaskGithubIssuesResponse,
        owner_module=_ITEM_MODULE,
        target_kinds=["global"],
    )
    _register_read(
        registry,
        "done_transition.registered_flow_ids",
        _dep.handle_registered_flow_ids,
        _dep.RegisteredFlowIdsRequest,
        _dep.RegisteredFlowIdsResponse,
        owner_module=_DEPLOY_MODULE,
        target_kinds=["global"],
    )
    _register_read(
        registry,
        "done_transition.latest_deployment_run",
        _dep.handle_latest_deployment_run,
        _dep.LatestDeploymentRunRequest,
        _dep.LatestDeploymentRunResponse,
        owner_module=_DEPLOY_MODULE,
        target_kinds=["item"],
    )
    _register_read(
        registry,
        "done_transition.run_stage",
        _dep.handle_run_stage,
        _dep.RunStageRequest,
        _dep.RunStageResponse,
        owner_module=_DEPLOY_MODULE,
        target_kinds=["global"],
    )
    _register_read(
        registry,
        "done_transition.run_blocking_qa",
        _dep.handle_run_blocking_qa,
        _dep.RunBlockingQaRequest,
        _dep.RunBlockingQaResponse,
        owner_module=_DEPLOY_MODULE,
        target_kinds=["global"],
    )
    _register_read(
        registry,
        "done_transition.done_preconditions",
        _dep.handle_done_preconditions,
        _dep.DonePreconditionsRequest,
        _dep.DonePreconditionsResponse,
        owner_module=_DEPLOY_MODULE,
        target_kinds=["item"],
    )


__all__ = ["register"]
