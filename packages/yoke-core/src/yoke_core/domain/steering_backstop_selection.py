"""Choose which unpicked work the steering backstop staffs, and what to tell it.

The backstop never replaces the people who open their own sessions and pull
work: it only notices work that stayed pickable and nobody picked.  Three
facts decide that, and all of them live here so the decision can be read
(and tested) without a database:

* nobody is already coming for it — no worker this backstop staffed for the
  same item is still on its way;
* it is old enough — it has been pickable for longer than the project's grace
  period, so a human had a real chance at it first;
* there is room — the project's concurrent-worker budget is not already spent
  on workers this backstop staffed and that are still running.

Everything else about a candidate (is it runnable, is it unclaimed, does its
route dispatch) is settled by the scheduler before a candidate reaches this
module.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Collection, Iterable, Sequence


_KEY_PREFIX = "steering-backstop:"

#: A worker this backstop staffed for the same item is still on its way.
WITHHELD_ALREADY_STAFFED = "already_staffed"

#: The candidate was pickable, but not for long enough yet.
WITHHELD_WITHIN_GRACE = "within_grace_period"

#: The candidate was old enough, but the scope has no worker headroom left.
WITHHELD_BUDGET_EXHAUSTED = "worker_budget_exhausted"


@dataclass(frozen=True)
class BackstopCandidate:
    """One runnable, unclaimed step the backstop could staff.

    ``unpicked_since`` is the moment the work became pickable — the later of
    its last change and the last time a claim on it was released — so the age
    measured against it is "how long has this sat there", not "how old is the
    item".
    """

    item_id: int
    item_ref: str
    title: str
    next_step: str
    rank: int
    unpicked_since: str

    def unpicked_seconds(self, now: str) -> int:
        return max(0, int((_parse(now) - _parse(self.unpicked_since)).total_seconds()))


@dataclass(frozen=True)
class WithheldCandidate:
    """A candidate the backstop deliberately did not staff, and why."""

    candidate: BackstopCandidate
    reason: str
    unpicked_seconds: int


@dataclass(frozen=True)
class BackstopSelection:
    """What one evaluation decided, before any launch is filed."""

    staff: tuple[BackstopCandidate, ...] = ()
    withheld: tuple[WithheldCandidate, ...] = ()
    workers_in_flight: int = 0
    worker_budget: int = 0
    headroom: int = 0

    def to_dict(self) -> dict:
        return {
            "staff": [_candidate_dict(item) for item in self.staff],
            "withheld": [
                {
                    **_candidate_dict(entry.candidate),
                    "reason": entry.reason,
                    "unpicked_seconds": entry.unpicked_seconds,
                }
                for entry in self.withheld
            ],
            "workers_in_flight": self.workers_in_flight,
            "worker_budget": self.worker_budget,
            "headroom": self.headroom,
        }


def _candidate_dict(candidate: BackstopCandidate) -> dict:
    return {
        "item_id": candidate.item_id,
        "item_ref": candidate.item_ref,
        "title": candidate.title,
        "next_step": candidate.next_step,
        "rank": candidate.rank,
        "unpicked_since": candidate.unpicked_since,
    }


def _parse(raw: str) -> datetime:
    parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def select_backstop_work(
    candidates: Iterable[BackstopCandidate],
    *,
    now: str,
    unpicked_after_seconds: int,
    worker_budget: int,
    staffed_item_ids: Collection[int] = (),
) -> BackstopSelection:
    """Rank-ordered staffing decision for one steering scope.

    ``staffed_item_ids`` is the work this backstop already has a worker coming
    for. Those items both spend the budget and are skipped, so a second
    evaluation moves on to the next gap instead of restaffing the one it
    already covered.
    """
    staffed = {int(item_id) for item_id in staffed_item_ids}
    headroom = max(0, int(worker_budget) - len(staffed))
    ordered: Sequence[BackstopCandidate] = sorted(
        candidates, key=lambda candidate: (candidate.rank, candidate.item_id)
    )
    staff: list[BackstopCandidate] = []
    withheld: list[WithheldCandidate] = []
    for candidate in ordered:
        age = candidate.unpicked_seconds(now)
        if candidate.item_id in staffed:
            withheld.append(WithheldCandidate(candidate, WITHHELD_ALREADY_STAFFED, age))
            continue
        if age < int(unpicked_after_seconds):
            withheld.append(WithheldCandidate(candidate, WITHHELD_WITHIN_GRACE, age))
            continue
        if len(staff) >= headroom:
            withheld.append(
                WithheldCandidate(candidate, WITHHELD_BUDGET_EXHAUSTED, age)
            )
            continue
        staff.append(candidate)
    return BackstopSelection(
        staff=tuple(staff),
        withheld=tuple(withheld),
        workers_in_flight=len(staffed),
        worker_budget=int(worker_budget),
        headroom=headroom,
    )


def backstop_instruction(
    candidate: BackstopCandidate,
    *,
    report_to_session_id: str,
) -> str:
    """Compose the whole brief a staffed worker gets.

    The report line is part of the instruction rather than a hook that
    rewrites the worker's output later: a worker that is told who to report
    to reports by construction, even when it ends in a way no hook observes.
    """
    return "\n".join(
        (
            f"/yoke {candidate.next_step} {candidate.item_ref}",
            "",
            f"Single-item mandate (steering backstop): execute only "
            f"{candidate.item_ref} to done. Do not pick up further work and "
            f"do not chain into other items.",
            "",
            "When it is done, report to the steering session that staffed you:",
            f"printf '%s' \"DONE {candidate.item_ref} <one-line summary>\" | "
            f"yoke say --stdin --session {report_to_session_id}",
            "",
            "Then end your session. If your claim is swept mid-work, "
            "reacquire it and continue.",
        )
    )


def backstop_idempotency_key(project_id: int, item_id: int) -> str:
    """One key per gap, so re-evaluating cannot double-launch it."""
    return f"{_KEY_PREFIX}{int(project_id)}:{int(item_id)}"


def backstop_gap_item_id(idempotency_key: str) -> int | None:
    """The item a backstop key names, or ``None`` when the key is not ours.

    Written and read in one module so the key stays the gap's identity rather
    than a format two call sites each half-remember.
    """
    raw = str(idempotency_key or "")
    if not raw.startswith(_KEY_PREFIX):
        return None
    parts = raw.split(":")
    if len(parts) != 3:
        return None
    try:
        return int(parts[2])
    except ValueError:
        return None


__all__ = [
    "BackstopCandidate",
    "BackstopSelection",
    "WITHHELD_ALREADY_STAFFED",
    "WITHHELD_BUDGET_EXHAUSTED",
    "WITHHELD_WITHIN_GRACE",
    "WithheldCandidate",
    "backstop_gap_item_id",
    "backstop_idempotency_key",
    "backstop_instruction",
    "select_backstop_work",
]
