"""The bound source commits a stage dispatches, or why it must not dispatch.

Declared external input bindings (a hosted consumer's trunk commit, say) are
resolved once when the run starts and recorded on it. Reading that record at
dispatch is what makes a retry, a fresh retrigger and the delivery record
agree: the branch is never consulted for a value again, so two dispatches of
one run cannot ship two different consumer commits.

A run freezes each bound source commit when it starts and never rebinds it,
so once a bound branch moves, a downstream check that proves the pair against
that branch's current head can only refuse — after the dispatched workflow
has spent its whole run getting there. The driver asks the control plane
immediately before dispatching a stage that consumes bound sources and fails
the stage at once instead, naming the stale source and the only remedy: a new
run, which binds the current commit.
"""

from __future__ import annotations

import sys
from typing import Any, Mapping, Optional

from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.control_plane_function_degradation import REGISTRY_SKEW_CODES
from yoke_core.domain.deployment_run_stale_bound_sources import (
    BOUND_SOURCES_CURRENT_FUNCTION_ID as FUNCTION_ID,
)


def stale_bound_source_refusal(run_id: str, stage_name: str) -> str:
    """The reason ``stage_name`` must not dispatch, or empty when it may."""
    response = call_dispatcher(
        function_id=FUNCTION_ID,
        target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
        payload={},
    )
    prefix = f"stage {stage_name!r} was not dispatched: "
    if not response.success:
        code = response.error.code if response.error else ""
        message = response.error.message if response.error else "request failed"
        if code in REGISTRY_SKEW_CODES:
            # The serving plane predates this check; the dispatch it would
            # have guarded proceeds exactly as it did before the check existed.
            print(
                f"  Bound source check: the control plane does not serve "
                f"{FUNCTION_ID} yet ({message}); dispatching without it",
                file=sys.stderr,
            )
            return ""
        return (
            f"{prefix}could not check whether run {run_id}'s bound sources are "
            f"current ({FUNCTION_ID} refused: {message}); repair that, then "
            f"re-drive {run_id}"
        )
    result = response.result or {}
    stale = [entry for entry in result.get("stale") or [] if entry.get("reason")]
    if stale:
        return prefix + "; ".join(str(entry["reason"]) for entry in stale)
    unverified = str(result.get("unverified") or "")
    if unverified:
        return (
            f"{prefix}could not confirm run {run_id}'s bound sources are current, "
            f"and dispatching blind could only fail later: {unverified}"
        )
    return ""


def bound_inputs_for_dispatch(
    config: Mapping[str, Any],
    *,
    name: str,
    run_id: str,
    bound_inputs: Optional[Mapping[str, str]],
) -> tuple[dict[str, str], str]:
    """The recorded commit for each input ``config`` binds, and any refusal."""
    resolved = dict(bound_inputs or {})
    declared = config.get("input_bindings") or {}
    if not declared:
        return resolved, ""
    missing = sorted(set(declared) - set(resolved))
    if missing:
        return resolved, (
            f"stage {name!r} declares input binding(s) {missing} that "
            f"deployment run {run_id} recorded no source commit for; start "
            "the run again so it resolves and records them before dispatch"
        )
    return resolved, stale_bound_source_refusal(run_id, name)


__all__ = ["bound_inputs_for_dispatch", "stale_bound_source_refusal"]
