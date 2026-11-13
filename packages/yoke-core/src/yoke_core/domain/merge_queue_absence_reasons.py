"""Why GitHub is not holding a landing, by its reported merge state."""

from __future__ import annotations


_ABSENCE_REASONS = {
    "dirty": (
        "it conflicts with its base branch — rebase the lane onto "
        "{target}, re-run the verification gate, and re-run `yoke merge item`"
    ),
    "behind": (
        "it is behind its base branch and the queue will not take it — "
        "rebase the lane onto {target} and re-run `yoke merge item`"
    ),
    "blocked": (
        "a required check, review, or protection rule is not satisfied — "
        "satisfy it and re-run `yoke merge item`"
    ),
    "draft": (
        "it is still a draft — mark it ready for review and re-run `yoke merge item`"
    ),
}

ARMED_READY_REASON = (
    "it is armed and ready but GitHub formed no queue entry — re-run "
    "`yoke merge item`, which enqueues it directly"
)
_DEFAULT_ABSENCE_REASON = (
    "GitHub reports it neither armed nor queued, with nothing in flight for "
    "it — address what the observation names and re-run `yoke merge item`"
)


def absence_reason(merge_state: str, *, target: str) -> str:
    """The named reason and recovery step for one ``mergeStateStatus``."""
    template = _ABSENCE_REASONS.get(merge_state.strip().lower(), _DEFAULT_ABSENCE_REASON)
    return template.format(target=target)


__all__ = ["ARMED_READY_REASON", "absence_reason"]
