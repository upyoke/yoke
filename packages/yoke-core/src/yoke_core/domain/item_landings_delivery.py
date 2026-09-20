"""Which release delivered each of an item's landings.

The item page lists a landing and then asks the question a reader has next:
did this one ship, and under what. That is the same question
:class:`~yoke_core.domain.release_delivery_summary.ReleaseCandidates` already
answers for the per-item count on a Frontier card, asked one landing at a
time, so it is that index -- not a second opinion about delivery -- doing the
work here. One index serves every landing: it resolves the project's releases
once and reuses the containment walk across each sha asked of it.

The item id is deliberately NOT passed to ``carrier_for``. That argument
short-circuits on run membership, which answers for the item as a whole: a run
that named the item before its newest merge existed would then be reported as
having delivered every landing, including ones that did not exist when it ran.
A landing is a commit, so it is answered as a commit -- honest carried work
first, then ancestry against the newest pinned lineage.

A landing no release carried and no release candidate contains is reported as
undelivered rather than unknown: the candidate set is every succeeded release
that could have carried it, so exhausting it is an answer.
"""

from __future__ import annotations

from typing import Any, Iterable

from yoke_core.domain.release_delivery_summary import ReleaseCandidates


def delivery_by_landing(
    conn: Any,
    *,
    merge_shas: Iterable[str],
    project_id: int,
    environment_id: Any,
    flow: str = "",
) -> dict[str, dict[str, str]]:
    """Map each landing's merge sha to the release that delivered it.

    A sha absent from the result was delivered by nothing.
    """
    shas = [str(sha).strip() for sha in merge_shas if str(sha).strip()]
    if not shas:
        return {}
    candidates = ReleaseCandidates(
        conn,
        project_id=int(project_id),
        environment_id=environment_id,
        flow=flow,
    )
    delivered: dict[str, dict[str, str]] = {}
    for sha in shas:
        carrier = candidates.carrier_for(sha)
        if carrier is not None:
            delivered[sha] = carrier
    return delivered


__all__ = ["delivery_by_landing"]
