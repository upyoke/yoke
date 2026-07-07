"""Chain-skip-memory filter helpers.

Owns the read-side of ``chain_skip_memory`` for both kinds of skip
entries — ``item_id`` (existing item dedupe filter) and ``process_key``
(disabled-process dedupe via policy merge). The decision engine's
suppression mechanism is the existing :class:`ProcessOfferPolicy`
disable; for memory-driven suppression we merge the recorded skip
keys into a copy of the active policy so the gate plumbing stays
single-pathed.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from yoke_core.api.routing_config import ProcessOfferPolicy


def merge_skip_memory_with_policy(
    policy: Optional[ProcessOfferPolicy],
    chain_skip_memory: Optional[List[Dict[str, Any]]],
) -> Optional[ProcessOfferPolicy]:
    """Treat chain_skip_memory.process_key entries as disabled in the effective policy.

    A subsequent offer in the same chain that finds a previously-skipped
    process key in chain_skip_memory must not re-recommend that process. The
    single suppression mechanism — the existing gate's policy disable — is
    applied to memory rather than live config by merging the skip set into
    a copy of the policy.
    """
    if not chain_skip_memory:
        return policy
    skip_keys = {
        str(e.get("process_key")).strip().lower()
        for e in chain_skip_memory
        if isinstance(e, dict) and e.get("process_key")
    }
    skip_keys.discard("")
    if not skip_keys:
        return policy
    merged_per_process = dict(policy.per_process) if policy is not None else {}
    merged_project = (
        dict(policy.shared_project_per_process) if policy is not None else {}
    )
    default_enabled = policy.default_enabled if policy is not None else False
    for k in skip_keys:
        # Disable at BOTH scopes: project policy outranks the machine
        # fallback, so a project-level enable must not resurrect a process
        # the chain already skipped.
        merged_per_process[k] = False
        merged_project[k] = False
    return ProcessOfferPolicy(
        default_enabled=default_enabled,
        per_process=merged_per_process,
        shared_project_per_process=merged_project,
        shared_project_default=(
            policy.shared_project_default if policy is not None else None
        ),
        shared_project_source=(
            policy.shared_project_source if policy is not None else None
        ),
    )


__all__ = ["merge_skip_memory_with_policy"]
