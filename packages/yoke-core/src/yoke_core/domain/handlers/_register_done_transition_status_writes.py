"""Register the internal done-transition status-flip writes.

These two ``done_transition.*`` write functions apply the status flips the
transport-aware done-transition engine relays instead of setting process-global
claim-bypass env vars: ``item_status_set`` flips ``item -> done`` (or redirects
to the delivery stage) and ``epic_task_status_set`` cascades an epic task to
``done``. Both post the claim bypass on a request-scoped ContextVar around the
unchanged domain write.

Both are ``adapter_status='internal'`` (merge finalize glue, never an agent CLI
surface), so they need no CLI adapter row, and both are
``ambient_session_required=False`` because the done transition runs in a merge
subprocess that may resolve no ambient harness session. They are
``claim_required_kind=None`` because the done ceremony intentionally bypasses
the item claim; the ``PROJECT`` + ``PERM_ITEMS_WRITE`` authorization scope
(``function_authz_product_scopes``) is what gates the bypass.
"""

from __future__ import annotations

from yoke_core.domain.handlers import done_transition_status_writes as _writes

_MODULE = "yoke_core.domain.handlers.done_transition_status_writes"


def register(registry) -> None:
    registry.register(
        "done_transition.item_status_set",
        _writes.handle_item_status_set,
        _writes.ItemStatusSetRequest,
        _writes.ItemStatusSetResponse,
        stability="stable",
        owner_module=_MODULE,
        target_kinds=["item"],
        side_effects=["item_status_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )
    registry.register(
        "done_transition.epic_task_status_set",
        _writes.handle_epic_task_status_set,
        _writes.EpicTaskStatusSetRequest,
        _writes.EpicTaskStatusSetResponse,
        stability="stable",
        owner_module=_MODULE,
        target_kinds=["item"],
        side_effects=["epic_task_status_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
