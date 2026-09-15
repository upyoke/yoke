"""Which QA target kinds this serving runtime can actually observe.

A QA stage reads its target from an earlier stage's receipt, so a target
kind with no registered receipt producer cannot be executed however
complete the rest of the release runtime is. That makes target-kind
support a separate axis from the definition schema version in
:mod:`deployment_flow_policy`, and the two move independently: a producer
arrives for one kind without changing the vocabulary, and the vocabulary
accepts a kind before anything can produce it.

Refusing here — at the gates that activate, update-active, assign and
start a definition — means raising the schema version never advertises a
kind that would only fail mid-run, after earlier stages had already
deployed. The producer's own mid-run refusal stays as defense-in-depth.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain import json_helper
from yoke_core.domain.deployment_flow_policy import QA_STEP_RUNNER, STAGE_KIND_QA


def unsupported_stage_target_kinds(stages: Any) -> tuple[str, ...]:
    """QA target kinds in *stages* that no receipt producer can observe.

    A QA stage reads its target from an earlier stage's receipt, so a kind
    with no registered producer cannot be executed however complete the
    rest of the runtime is. Reported separately from the schema version
    because the two axes move independently: a producer arrives for one
    kind without changing the vocabulary, and the vocabulary can accept a
    kind before anything can produce it.

    Accepts the decoded stage list or the JSON its callers hold, because
    both are live shapes on the definition paths this guards — and a
    shape it cannot read raises rather than reporting "nothing
    unsupported", which is the one answer that would let an
    unobservable target through.
    """
    from yoke_core.domain.deploy_pipeline_stage_receipt_producers import (
        RECEIPT_PRODUCERS,
    )

    if isinstance(stages, str):
        stages = json_helper.loads_text(stages)
    if not isinstance(stages, list):
        raise ValueError(
            "deployment flow stages must be a list to check target support; "
            f"got {type(stages).__name__}"
        )
    unsupported: list[str] = []
    for stage in stages:
        if not isinstance(stage, Mapping):
            continue
        if stage.get("stage_kind") != STAGE_KIND_QA and stage.get(
            "step_runner"
        ) != QA_STEP_RUNNER:
            continue
        target = stage.get("target")
        if not isinstance(target, Mapping):
            continue
        kind = str(target.get("kind") or "")
        if kind and kind not in RECEIPT_PRODUCERS and kind not in unsupported:
            unsupported.append(kind)
    return tuple(unsupported)


def require_supported_stage_targets(stages: Any, *, operation: str) -> None:
    """Refuse a definition whose QA target kinds have no producer.

    Raised at the same gates the schema version guards — activating,
    updating an active definition, assigning, starting — so an unsupported
    kind is refused before a run exists rather than after earlier stages
    have already deployed. The mid-run producer refusal stays as
    defense-in-depth.
    """
    unsupported = unsupported_stage_target_kinds(stages)
    if not unsupported:
        return
    listed = ", ".join(sorted(unsupported))
    raise ValueError(
        f"{operation} names QA target kind(s) {listed} that no receipt "
        "producer in this serving runtime can observe; keep the definition "
        "disabled until a producer for that kind is registered in "
        "deploy_pipeline_stage_receipt_producers.RECEIPT_PRODUCERS"
    )


__all__ = [
    "require_supported_stage_targets",
    "unsupported_stage_target_kinds",
]
