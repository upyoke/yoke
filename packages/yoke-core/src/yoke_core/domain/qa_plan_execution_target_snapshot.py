"""Validation helpers for durable QA plan execution target snapshots."""

from __future__ import annotations

import json
from typing import Any, Mapping


def execution_target_for_roster(
    roster: list[dict[str, Any]],
) -> tuple[dict[str, Any], str]:
    """Require every case to carry the same immutable execution target."""
    from yoke_core.domain.qa_plan_execution_store import (
        QaPlanExecutionStateError,
        canonical,
    )

    targets = [row.get("execution_target") for row in roster]
    digests = [str(row.get("execution_target_digest") or "") for row in roster]
    if (
        not targets
        or any(not isinstance(target, dict) for target in targets)
        or any(not digest for digest in digests)
    ):
        raise QaPlanExecutionStateError(
            "materialized QA roster lacks an execution environment target"
        )
    if len({canonical(target) for target in targets}) != 1 or len(set(digests)) != 1:
        raise QaPlanExecutionStateError(
            "materialized QA roster mixes execution environment targets"
        )
    target = dict(targets[0])
    from yoke_core.domain.qa_execution_environment_target import (
        require_runtime_target,
        target_digest,
    )

    if target_digest(target) != digests[0]:
        raise QaPlanExecutionStateError(
            "materialized QA roster target digest does not match"
        )
    require_runtime_target(target)
    return target, digests[0]


def decode_execution_target(
    execution: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Decode one persisted execution target without accepting non-objects."""
    raw_target = execution.get("execution_target_json")
    if not raw_target:
        return None
    from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError

    try:
        target = json.loads(str(raw_target))
    except (TypeError, ValueError) as exc:
        raise QaPlanExecutionStateError(
            "QA plan execution contains an invalid target snapshot"
        ) from exc
    if not isinstance(target, dict):
        raise QaPlanExecutionStateError(
            "QA plan execution contains an invalid target snapshot"
        )
    from yoke_core.domain.qa_execution_environment_target import target_digest

    stored_digest = str(execution.get("execution_target_digest") or "")
    if not stored_digest or target_digest(target) != stored_digest:
        raise QaPlanExecutionStateError(
            "QA plan execution target snapshot digest does not match"
        )
    return target


__all__ = ["decode_execution_target", "execution_target_for_roster"]
