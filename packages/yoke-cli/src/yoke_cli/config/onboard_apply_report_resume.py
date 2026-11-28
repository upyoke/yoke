"""How a resumed apply report carries an earlier pass's step receipts.

A resume rebuilds the Review plan, so plan positions shift between passes and
a step's ordinal says nothing about which earlier row it continues. A current
row takes the earlier row with its own action and target, one to one.
Completed earlier rows no current row continues are kept after the current
rows as history under a ``prior-`` step id; the report writer never updates
them as current progress.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_contracts.timestamps import format_instant

#: Completed step statuses; the apply report re-exports both.
STATUS_DONE = "done"
STATUS_SKIPPED = "skipped"
#: Step ids of earlier-pass receipts kept after the current plan.
PRIOR_STEP_PREFIX = "prior-"


def is_prior_step(step: Mapping[str, Any]) -> bool:
    """Whether a report row is an earlier pass's receipt kept for history."""
    return str(step.get("step_id") or "").startswith(PRIOR_STEP_PREFIX)


def merge_resume_steps(
    steps: list[dict[str, Any]],
    resume_payload: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Carry an earlier pass's completed receipts onto this pass's plan.

    A row matches the earlier row with the same action and target, one to
    one; plan positions shift between passes, so the ordinal in ``step_id``
    never decides a match. Completed earlier rows no current row matches stay
    after the current rows as history, under a ``prior-`` id.
    """
    prior = [
        step for step in resume_payload.get("steps", []) if isinstance(step, Mapping)
    ]
    used: set[int] = set()
    for step in steps:
        for index, old in enumerate(prior):
            if index in used or is_prior_step(old):
                continue
            if (old.get("action"), old.get("target")) != (
                step.get("action"),
                step.get("target"),
            ):
                continue
            used.add(index)
            if old.get("status") in (STATUS_DONE, STATUS_SKIPPED):
                _copy_receipt(step, old)
            break
    taken = {str(step["step_id"]) for step in steps}
    history: list[dict[str, Any]] = []
    for index, old in enumerate(prior):
        if index in used or old.get("status") not in (STATUS_DONE, STATUS_SKIPPED):
            continue
        kept = dict(old)
        kept["step_id"] = _prior_step_id(str(old.get("step_id") or ""), taken)
        for clock in ("started_at", "finished_at"):
            value = kept.get(clock)
            kept[clock] = None if value is None else format_instant(value)
        history.append(kept)
    return steps + history


def _copy_receipt(step: dict[str, Any], old: Mapping[str, Any]) -> None:
    if "detail" in old:
        step["detail"] = old["detail"]
    step["status"] = old.get("status")
    for clock in ("started_at", "finished_at"):
        value = old.get(clock)
        step[clock] = None if value is None else format_instant(value)


def _prior_step_id(step_id: str, taken: set[str]) -> str:
    base = step_id if step_id.startswith(PRIOR_STEP_PREFIX) else PRIOR_STEP_PREFIX + step_id
    candidate, number = base, 2
    while candidate in taken:
        candidate, number = f"{base}-{number}", number + 1
    taken.add(candidate)
    return candidate


__all__ = ["PRIOR_STEP_PREFIX", "is_prior_step", "merge_resume_steps"]
