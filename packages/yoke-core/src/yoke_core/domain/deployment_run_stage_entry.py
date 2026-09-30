"""When a live deployment run entered the stage it is currently sitting at.

A stage's own receipt is allocated as that stage starts, so the newest
receipt's ``created_at`` is when the run entered it. A QA stage has no
receipt of its own to read at all —
:func:`~yoke_core.domain.deployment_stage_receipts.allocate_deployment_stage_receipt`
refuses a QA stage by name — so a run parked at scoped QA is dated from the
newest completion among the receipt-producing stages its flow orders before
that stage: the moment the run advanced into the stage it is now waiting at.

Dating such a run from its own ``started_at`` reported the age of the whole
run as the age of its current stage, so a run ten minutes into item QA was
shown as an hour-long stall and read as one. That reading is truthful only
while no receipt exists at all, which is a run that has not left its first
stage, so callers keep it as the last resort and nothing else.

The ordering here is the flow's pinned stage list, never elapsed time: a
stage name the run's flow does not pin cannot be placed relative to the
current one, and contributes no evidence rather than a guessed order.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from typing import Any

from yoke_core.domain.deployment_flow_policy import QA_STEP_RUNNER, STAGE_KIND_QA


def parse_stage_plan(raw: Any) -> tuple[dict[str, Any], ...]:
    """The flow's pinned stages in order; unreadable JSON yields no stages."""
    try:
        stages = json.loads(str(raw or "[]"))
    except (TypeError, ValueError):
        return ()
    if not isinstance(stages, list):
        return ()
    return tuple(dict(stage) for stage in stages if isinstance(stage, Mapping))


def _uniquely_pinned(
    stages: tuple[dict[str, Any], ...], stage_name: str
) -> dict[str, Any] | None:
    matches = [
        stage for stage in stages if str(stage.get("name") or "") == stage_name
    ]
    return matches[0] if len(matches) == 1 else None


def is_scoped_qa_stage(stages: tuple[dict[str, Any], ...], stage_name: str) -> bool:
    """Whether the named stage is the flow's scoped-QA stage."""
    stage = _uniquely_pinned(stages, stage_name)
    if stage is None:
        return False
    return (
        stage.get("stage_kind") == STAGE_KIND_QA
        and stage.get("step_runner") == QA_STEP_RUNNER
    )


def preceding_stage_names(
    stages: tuple[dict[str, Any], ...], stage_name: str
) -> frozenset[str]:
    """Stage names the flow orders before ``stage_name``.

    A stage the flow does not uniquely pin cannot be ordered against, so the
    answer is empty rather than an assumed position.
    """
    if _uniquely_pinned(stages, stage_name) is None:
        return frozenset()
    before: set[str] = set()
    for stage in stages:
        name = str(stage.get("name") or "")
        if name == stage_name:
            break
        if name:
            before.add(name)
    return frozenset(before)


def stage_entry_times(
    receipts: Iterable[Mapping[str, Any]],
    *,
    current_stage_by_run: Mapping[str, str],
    stage_plan_by_run: Mapping[str, tuple[dict[str, Any], ...]],
) -> dict[str, str]:
    """Each run's current-stage entry timestamp, from receipt evidence only.

    ``receipts`` carries ``run_id``, ``stage_name``, ``created_at``,
    ``completed_at`` and ``id`` for every receipt of the runs in question. A
    run with no usable receipt is absent from the result, which is the
    caller's signal that receipts prove nothing about its stage age.
    """
    own: dict[str, tuple[str, int]] = {}
    after_prior: dict[str, str] = {}
    for receipt in receipts:
        run_id = str(receipt["run_id"])
        at_stage = current_stage_by_run.get(run_id)
        if not at_stage:
            continue
        stage_name = str(receipt["stage_name"] or "")
        if stage_name == at_stage:
            started = str(receipt.get("created_at") or "")
            if not started:
                continue
            attempt = (started, int(receipt["id"]))
            if attempt > own.get(run_id, ("", 0)):
                own[run_id] = attempt
            continue
        if stage_name not in preceding_stage_names(
            stage_plan_by_run.get(run_id, ()), at_stage
        ):
            continue
        finished = str(receipt.get("completed_at") or "")
        if finished > after_prior.get(run_id, ""):
            after_prior[run_id] = finished
    entered = {run_id: started for run_id, (started, _id) in own.items()}
    for run_id, finished in after_prior.items():
        entered.setdefault(run_id, finished)
    return entered


__all__ = [
    "is_scoped_qa_stage",
    "parse_stage_plan",
    "preceding_stage_names",
    "stage_entry_times",
]
