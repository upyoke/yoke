"""Evaluator helpers for ``master_plan_check``.

This module is the evaluator leg of the parser/evaluator/reporter
triplet that backs ``yoke_core.domain.master_plan_check``. It owns:

- ``validate_frontier_order`` — flag pairs in the remaining frontier
  where a later-ordered entry has outrun an earlier enabling one.
- ``validate_prerequisite_prose`` — flag prose relationships where the
  dependent has outrun its stated blocker.

Both validators are read-only; they take parsed shapes plus a status
map and emit ``Contradiction`` records. ``Contradiction``,
``FrontierEntry``, and ``ProseRelationship`` are owned by the
entry-point module and imported via deferred imports inside functions
to avoid a circular import. ``status_rank`` and ``_STATUS_RANK`` also
live in the entry-point.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

if TYPE_CHECKING:
    from yoke_core.domain.master_plan_check import (
        Contradiction,
        FrontierEntry,
        ProseRelationship,
    )


def validate_frontier_order(
    remaining: List["FrontierEntry"],
    statuses: Dict[str, Optional[str]],
) -> Tuple[List["Contradiction"], List[str]]:
    """Flag pairs where a later-ordered entry has outrun an earlier one.

    Returns ``(contradictions, advisories)``.

    Contract:

    - Only inspect the *remaining* frontier section. The landed section
      is already historical and its ordering is not enforced.
    - If an earlier entry is past ``implemented``/``release``/``done``,
      treat the earlier enabling work as complete — later items are
      free to move. No drift.
    - If either earlier or later has no live status (unknown id or
      ``None`` row), emit an advisory and skip the pair.
    - Otherwise compare status ranks. If the later entry's rank is
      strictly greater than the earlier entry's, emit an
      ``ordered_frontier_drift`` contradiction.
    """
    from yoke_core.domain.master_plan_check import (
        Contradiction,
        _STATUS_RANK,
        status_rank,
    )

    contradictions: List[Contradiction] = []
    advisories: List[str] = []

    if not remaining:
        return contradictions, advisories

    for i, earlier in enumerate(remaining):
        earlier_status = statuses.get(earlier.yok_id)
        earlier_rank = status_rank(earlier_status)
        if earlier_status is None:
            advisories.append(
                f"{earlier.yok_id} appears in remaining frontier but has "
                f"no live status — strategize cannot validate its ordering."
            )
            continue
        if earlier_rank is None:
            advisories.append(
                f"{earlier.yok_id} has exceptional status '{earlier_status}' — "
                f"skipping ordered-frontier comparison."
            )
            continue
        # Earlier item already past implemented → later items are free.
        if earlier_rank >= _STATUS_RANK["implemented"]:
            continue

        for later in remaining[i + 1 :]:
            later_status = statuses.get(later.yok_id)
            later_rank = status_rank(later_status)
            if later_status is None or later_rank is None:
                # Skip unknown later; dedicated advisory only when the
                # later id is unknown altogether.
                if later_status is None:
                    advisories.append(
                        f"{later.yok_id} appears in remaining frontier but "
                        f"has no live status — skipping ordered-frontier "
                        f"comparison against {earlier.yok_id}."
                    )
                continue
            if later_rank > earlier_rank:
                contradictions.append(
                    Contradiction(
                        kind="ordered_frontier_drift",
                        earlier=earlier.yok_id,
                        earlier_status=earlier_status,
                        later=later.yok_id,
                        later_status=later_status,
                        detail=(
                            f"{later.yok_id} is at '{later_status}' but the "
                            f"plan orders it after {earlier.yok_id} which is "
                            f"still at '{earlier_status}'. Later frontier "
                            f"item has outrun the earlier enabling slice."
                        ),
                    )
                )

    return contradictions, advisories


def validate_prerequisite_prose(
    relationships: List["ProseRelationship"],
    statuses: Dict[str, Optional[str]],
) -> Tuple[List["Contradiction"], List[str]]:
    """Flag prose relationships where the dependent has outrun its blocker."""
    from yoke_core.domain.master_plan_check import (
        Contradiction,
        _STATUS_RANK,
        status_rank,
    )

    contradictions: List[Contradiction] = []
    advisories: List[str] = []

    for rel in relationships:
        blocker_status = statuses.get(rel.blocker)
        dependent_status = statuses.get(rel.dependent)
        blocker_rank = status_rank(blocker_status)
        dependent_rank = status_rank(dependent_status)

        if blocker_status is None or dependent_status is None:
            advisories.append(
                f"Prose says {rel.dependent} {rel.keyword} {rel.blocker}, "
                f"but one of the items has no live status — skipping "
                f"prose comparison."
            )
            continue
        if blocker_rank is None or dependent_rank is None:
            advisories.append(
                f"Prose {rel.dependent} {rel.keyword} {rel.blocker} has an "
                f"exceptional status — skipping prose comparison."
            )
            continue

        # Blocker already past implemented → dependent is free to move.
        if blocker_rank >= _STATUS_RANK["implemented"]:
            continue

        if dependent_rank > blocker_rank:
            contradictions.append(
                Contradiction(
                    kind="prerequisite_prose_drift",
                    earlier=rel.blocker,
                    earlier_status=blocker_status,
                    later=rel.dependent,
                    later_status=dependent_status,
                    detail=(
                        f"Plan prose says {rel.dependent} {rel.keyword} "
                        f"{rel.blocker}, but {rel.dependent} is at "
                        f"'{dependent_status}' while {rel.blocker} is "
                        f"still at '{blocker_status}'. Dependent has "
                        f"outrun its stated prerequisite."
                    ),
                )
            )

    return contradictions, advisories
