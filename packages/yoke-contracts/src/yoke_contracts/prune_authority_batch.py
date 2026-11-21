"""Per-lane validation for the batched prune-authority read.

One malformed lane used to reject the whole batch, so every other terminal
lane on the machine stayed on disk. Each lane is judged on its own. An
invalid lane is not prunable and names how to correct it. Every valid lane
still receives a verdict.
"""

from __future__ import annotations

from typing import Any, Callable


LANE_INVALID = "lane_invalid"


class PruneBatchInvalid(Exception):
    """The payload is not a list of lanes, so there is nothing to judge."""


def lane_invalid_reason(detail: str) -> str:
    """Why one lane was skipped, and the recovery that retries the rest."""
    problem = detail or "the lane record could not be read"
    return (
        f"{LANE_INVALID}: {problem}. "
        "Correct this lane — a detached worktree is detached@<commit>, not "
        "an empty branch — and rerun HC-worktree-health. "
        "The other lanes in this batch were still judged."
    )


def _validation_detail(exc: Exception) -> str:
    text = " ".join(str(exc).split())
    if len(text) > 180:
        text = text[:180].rstrip()
    return text


def verdicts_for_lanes(
    payload: object,
    *,
    validate: Callable[[object], Any],
    judge_all: Callable[[list[Any]], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Judge each lane. Raise :class:`PruneBatchInvalid` when ``lanes`` is not a list.

    ``judge_all`` sees only the lanes that validated, in order, and returns
    one verdict each. It is not called when every lane is invalid, so a
    batch of bad records does not open the control plane.
    """
    lanes = payload.get("lanes") if isinstance(payload, dict) else None
    if not isinstance(lanes, list):
        raise PruneBatchInvalid(
            "prune authority payload invalid: lanes must be a list. "
            "Send one object per lane and retry the read."
        )
    parsed: list[Any] = []
    invalid: dict[int, dict[str, Any]] = {}
    for index, lane in enumerate(lanes):
        try:
            parsed.append(validate(lane))
        except Exception as exc:  # noqa: BLE001 - one bad lane stays one bad lane
            parsed.append(None)
            invalid[index] = {
                "prunable": False,
                "reason": lane_invalid_reason(_validation_detail(exc)),
            }
    valid = [lane for lane in parsed if lane is not None]
    judged = list(judge_all(valid)) if valid else []
    if len(judged) != len(valid):
        raise PruneBatchInvalid(
            f"prune authority judged {len(judged)} of {len(valid)} valid lanes. "
            "Retry the read."
        )
    verdicts: list[dict[str, Any]] = []
    cursor = 0
    for index, lane in enumerate(parsed):
        if lane is None:
            verdicts.append(invalid[index])
            continue
        verdicts.append(judged[cursor])
        cursor += 1
    return verdicts


__all__ = [
    "LANE_INVALID",
    "PruneBatchInvalid",
    "lane_invalid_reason",
    "verdicts_for_lanes",
]
