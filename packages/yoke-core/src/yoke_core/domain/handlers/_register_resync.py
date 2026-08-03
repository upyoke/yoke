"""Register the internal resync detection/repair control-plane functions.

These ``resync.*`` functions are the control-plane reads and one write the
transport-aware resync engine relays so its Stage-1 linkage, Stage-2
comparison, and repair-mode reads/write run over an https control plane as
well as a local Postgres connection. Every function is
``adapter_status='internal'`` (engine glue, never an agent CLI surface),
so none carry a CLI adapter row.

The reads are ``claim_required_kind=None`` and declare no side effects, so
authorization falls through to the machine-local read allowance. The one
write (``epic_task_github_issue_set``) is ``claim_required_kind=None``
because the inline write it replaces was claim-free, and
``ambient_session_required=False`` because a resync run may resolve no
ambient harness session; its ``PROJECT`` + ``PERM_ITEMS_WRITE`` scope
(``function_authz_product_scopes``) gates the write.
"""

from __future__ import annotations

from yoke_core.domain.handlers import resync_compare_reads as _compare
from yoke_core.domain.handlers import resync_detect_reads as _detect
from yoke_core.domain.handlers import resync_repair_reads as _repair_reads
from yoke_core.domain.handlers import resync_repair_writes as _repair_writes

_DETECT_MODULE = "yoke_core.domain.handlers.resync_detect_reads"
_COMPARE_MODULE = "yoke_core.domain.handlers.resync_compare_reads"
_REPAIR_READS_MODULE = "yoke_core.domain.handlers.resync_repair_reads"
_REPAIR_WRITES_MODULE = "yoke_core.domain.handlers.resync_repair_writes"


def _register_read(
    registry,
    function_id,
    handler,
    request_model,
    response_model,
    *,
    owner_module,
) -> None:
    registry.register(
        function_id,
        handler,
        request_model,
        response_model,
        stability="stable",
        owner_module=owner_module,
        target_kinds=["global"],
        side_effects=[],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
    )


def register(registry) -> None:
    _register_read(
        registry,
        "resync.linkage_roster",
        _detect.handle_linkage_roster,
        _detect.LinkageRosterRequest,
        _detect.LinkageRosterResponse,
        owner_module=_DETECT_MODULE,
    )
    _register_read(
        registry,
        "resync.linkage_rows",
        _detect.handle_linkage_rows,
        _detect.LinkageRowsRequest,
        _detect.LinkageRowsResponse,
        owner_module=_DETECT_MODULE,
    )
    _register_read(
        registry,
        "resync.compare_prefetch",
        _compare.handle_compare_prefetch,
        _compare.ComparePrefetchRequest,
        _compare.ComparePrefetchResponse,
        owner_module=_COMPARE_MODULE,
    )
    _register_read(
        registry,
        "resync.item_lookup",
        _repair_reads.handle_item_lookup,
        _repair_reads.ItemLookupRequest,
        _repair_reads.ItemLookupResponse,
        owner_module=_REPAIR_READS_MODULE,
    )
    _register_read(
        registry,
        "resync.epic_task_repair_read",
        _repair_reads.handle_epic_task_repair_read,
        _repair_reads.EpicTaskRepairReadRequest,
        _repair_reads.EpicTaskRepairReadResponse,
        owner_module=_REPAIR_READS_MODULE,
    )
    _register_read(
        registry,
        "resync.epic_task_body",
        _repair_reads.handle_epic_task_body,
        _repair_reads.EpicTaskBodyRequest,
        _repair_reads.EpicTaskBodyResponse,
        owner_module=_REPAIR_READS_MODULE,
    )
    registry.register(
        "resync.epic_task_github_issue_set",
        _repair_writes.handle_epic_task_github_issue_set,
        _repair_writes.EpicTaskGithubIssueSetRequest,
        _repair_writes.EpicTaskGithubIssueSetResponse,
        stability="stable",
        owner_module=_REPAIR_WRITES_MODULE,
        target_kinds=["item"],
        side_effects=["epic_task_github_issue_write"],
        emitted_event_names=["YokeFunctionCalled"],
        guardrails=[],
        adapter_status="internal",
        claim_required_kind=None,
        ambient_session_required=False,
    )


__all__ = ["register"]
