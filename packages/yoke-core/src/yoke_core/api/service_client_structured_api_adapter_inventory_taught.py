"""Taught-but-unregistered Yoke CLI adapter inventory.

Sibling of :mod:`service_client_structured_api_adapter_inventory`. Holds
the subcommands that Yoke skill prose and harness orientation teach
but that do not yet have a registered function id. The registered-
function cutover moves rows out of this inventory as handlers land.

Each entry carries a sentinel ``function_id`` beginning with
``"internal."`` so the shell-quoted-function-payload lint can match
the subcommand path against the inventory and avoid the "no function
id covers this exact subcommand path" denial — even though no live
handler exists yet. NOT covered by the registry-parity matrix; the
parent inventory's :data:`CLI_ADAPTERS` is the parity surface.

When a registered function id lands for one of these subcommands, move
the entry to :data:`CLI_ADAPTERS` with the real function id and remove
it from this list.
"""

from __future__ import annotations

from typing import List

from yoke_core.api.service_client_structured_api_adapter_inventory import (
    AdapterEntry,
)


_NOTE = (
    "taught by /yoke skills and harness orientation; no registered "
    "function id yet. Inventory entry "
    "exists so the shell-quoted-function-payload lint recognises the "
    "subcommand path."
)


def _service_client_taught() -> List[AdapterEntry]:
    """Session + orchestration adapters taught by ``/yoke do`` etc."""
    sc = "python3 -m yoke_core.api.service_client"
    reads = (
        ("evaluate-gate", "evaluate_gate"),
        ("plan-candidates", "plan_candidates"),
        ("path-claim-list", "path_claim_list"),
        ("path-claim-get", "path_claim_get"),
        ("path-claim-conflicts", "path_claim_conflicts"),
        ("path-claim-boundary", "path_claim_boundary"),
        ("path-claim-unblock-stranded", "path_claim_unblock_stranded"),
    )
    writes = (
        ("session-heartbeat", "session_heartbeat"),
        ("session-end", "session_end"),
        ("session-end-if-empty", "session_end_if_empty"),
        ("session-begin", "session_begin"),
        ("apply-approval", "apply_approval"),
        ("path-claim-activate", "path_claim_activate"),
    )
    out: List[AdapterEntry] = []
    for sub, slug in reads:
        out.append(AdapterEntry(
            function_id=f"internal.service_client.{slug}",
            cli_invocation=f"{sc} {sub}",
            notes=_NOTE,
            read_shape=True,
        ))
    for sub, slug in writes:
        out.append(AdapterEntry(
            function_id=f"internal.service_client.{slug}",
            cli_invocation=f"{sc} {sub}",
            notes=_NOTE,
        ))
    return out


def _db_router_epic_reads() -> List[AdapterEntry]:
    """Read-shape ``db_router epic`` subcommands surfaced live."""
    base = "python3 -m yoke_core.cli.db_router epic"
    subs = (
        ("task-get-body", "epic_task_get_body"),
        ("review-get", "epic_review_get"),
        ("file-list", "epic_file_list"),
        ("submission-receipt-get", "epic_submission_receipt_get"),
        ("progress-note-list-unsynced", "epic_progress_note_list_unsynced"),
    )
    return [
        AdapterEntry(
            function_id=f"internal.db_router.{slug}",
            cli_invocation=f"{base} {sub}",
            notes=_NOTE,
            read_shape=True,
        )
        for sub, slug in subs
    ]


def _db_router_query_read() -> List[AdapterEntry]:
    """Read-shape ``db_router query`` SQL escape hatch.

    Read-only SQL is always permitted per CLAUDE.md; the matching
    function-call surface is read-by-shape, not read-by-handler. Without
    this entry, ``db_router query "..." 2>&1`` falls through to the
    domain-only branch which forbids bare ``2>&1`` (the "no consumer at
    all" heuristic). Read-only operator/debug queries legitimately
    redirect stderr-to-stdout to inspect both streams.
    """
    return [
        AdapterEntry(
            function_id="internal.db_router.query",
            cli_invocation="python3 -m yoke_core.cli.db_router query",
            notes=_NOTE,
            read_shape=True,
        )
    ]


TAUGHT_ADAPTERS: List[AdapterEntry] = (
    _service_client_taught() + _db_router_epic_reads() + _db_router_query_read()
)


__all__ = ["TAUGHT_ADAPTERS"]
