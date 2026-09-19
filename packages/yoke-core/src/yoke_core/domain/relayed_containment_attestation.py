"""The lane's containment answer, carried to the server that cannot look.

A control plane serving an https project holds no checkout of that project.
Its repository reader answers ancestry exactly and content only weakly, so
there are real containment questions it can only call undetermined — and an
undetermined containment is a done gate that refuses a correctly delivered
item until someone redeploys, which makes every other member of that release
fail the same way.

The client standing in the lane can answer those questions exactly, so it
attests the verdict with its terminal transition
(:mod:`lane_containment_attestation`). This module is the server's half:
bind the attestation for the duration of the write, hand it to the gate that
asks, and record what it decided on the item's delivery record.

Two properties keep the relay honest. It is consulted ONLY where the
server's own sources came back undetermined, so a host that can see decides
for itself and a client cannot talk over it. And it answers only about the
exact pair it attested — the same candidate revision and the same commit —
so an attestation taken against some other release is ignored rather than
mistaken for this one.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Iterator, Mapping, Optional, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_run_candidate_containment import (
    CONTAINED,
    NOT_CONTAINED,
    ContainmentVerdict,
)
from yoke_core.domain.schema_common import _column_exists, _table_exists


SOURCE_RELAYED_LANE = "relayed_lane_checkout"

_RELAYED: ContextVar[tuple[Mapping[str, Any], ...]] = ContextVar(
    "relayed_containment_attestations", default=()
)


@contextmanager
def relayed_attestations_bound(
    attestations: Optional[Sequence[Mapping[str, Any]]],
) -> Iterator[None]:
    """Bind a caller's lane attestations for the duration of its write.

    A sequence because one close-out answers more than one question: the
    done gate asks containment of the item's recorded merge AND of its live
    lane head, and the lane can see both.
    """
    bound = tuple(dict(entry) for entry in attestations or () if entry)
    token = _RELAYED.set(bound)
    try:
        yield
    finally:
        _RELAYED.reset(token)


def matching_attestation(
    *, candidate: str, commit_sha: str
) -> Optional[dict[str, Any]]:
    """The relayed attestation about exactly this pair, if one arrived.

    Matching is on both commits because an attestation is an answer about
    one pair. A verdict taken against a different candidate says nothing
    about this one, and using it anyway would be the same confident guess
    this whole surface exists to stop making.
    """
    for entry in _RELAYED.get():
        if not any(
            _same_commit(entry.get(key), candidate)
            for key in ("candidate_sha", "candidate_ref")
        ):
            continue
        if _same_commit(entry.get("commit_sha"), commit_sha):
            return dict(entry)
    return None


def relayed_verdict(*, candidate: str, commit_sha: str) -> Optional[ContainmentVerdict]:
    """The lane's answer to exactly this question, or ``None``."""
    bound = matching_attestation(candidate=candidate, commit_sha=commit_sha)
    if not bound:
        return None
    state = str(bound.get("state") or "")
    if state not in {CONTAINED, NOT_CONTAINED}:
        return None
    return ContainmentVerdict(
        state,
        reason=(
            "the lane checkout answered by "
            f"{bound.get('method') or 'an unnamed test'}"
        ),
        source=SOURCE_RELAYED_LANE,
    )


def take_relayed_verdict(
    verdict: ContainmentVerdict,
    conn: Any,
    *,
    item_id: int,
    run_id: str,
    candidate: str,
    commit_sha: str,
) -> ContainmentVerdict:
    """Replace an undetermined verdict with the lane's, and record it.

    The caller has already established that its own sources could not
    answer; this is the one place that decision is turned into the relayed
    one, so the "only when the server cannot answer" rule holds in a single
    readable step rather than at each gate that asks.
    """
    relayed = relayed_verdict(candidate=candidate, commit_sha=commit_sha)
    if relayed is None:
        return verdict
    attestation = matching_attestation(candidate=candidate, commit_sha=commit_sha)
    if attestation and item_id:
        record_attestation(
            conn, item_id=int(item_id), run_id=run_id, attestation=attestation
        )
    return relayed


def record_attestation(
    conn: Any,
    *,
    item_id: int,
    run_id: str,
    attestation: Mapping[str, Any],
) -> bool:
    """Store the relayed evidence on the item's delivery record for that run.

    Durable because the verdict outlives the transition that carried it: the
    next reader of this item's delivery — a re-entered close-out, an
    operator asking why it passed — has to be able to see which commits were
    compared, which test answered, and when, without the lane that answered
    still existing.

    ``False`` when this control plane keeps no such record (no delivery-run
    tables, or a run this item was never enrolled in). The verdict is not
    weakened by that; only the audit trail is, and the caller has already
    decided on the verdict itself.
    """
    if not run_id or not _has_column(conn):
        return False
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    document = json.dumps(
        {**dict(attestation), "recorded_at": iso8601_now()},
        sort_keys=True,
    )
    cursor = conn.execute(
        "UPDATE deployment_run_items SET containment_attestation = "
        f"{marker} WHERE run_id = {marker} AND item_id = {marker}",
        (document, str(run_id), int(item_id)),
    )
    conn.commit()
    return bool(getattr(cursor, "rowcount", 0))


def _has_column(conn: Any) -> bool:
    return _table_exists(conn, "deployment_run_items") and _column_exists(
        conn, "deployment_run_items", "containment_attestation"
    )


def _same_commit(attested: Any, asked: str) -> bool:
    left = str(attested or "").strip().lower()
    right = str(asked or "").strip().lower()
    return bool(left) and left == right


__all__ = [
    "SOURCE_RELAYED_LANE",
    "matching_attestation",
    "record_attestation",
    "relayed_attestations_bound",
    "relayed_verdict",
    "take_relayed_verdict",
]
