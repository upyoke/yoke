"""What a takeover reads before it locks the older run's row.

Whether the new candidate contains the older one is a commit comparison on
the repository host, and the removal's QA cleanup asks which shared groups
the remaining members attach. Both are read here with no run lock held. The
takeover then locks the older run and re-checks them in constant time: the
older run's recorded lineage, eligibility and the projection's fingerprint.
A change committed in between refuses the attempt before any ownership write.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain.project_identity import render_item_ref


@dataclass
class TakeoverRead:
    """The containment verdict and removal projection, read unlocked."""

    old_lineage: str
    verdict: Any
    projection: Any


def _verdict(conn: Any, new_run: Mapping[str, Any], old_lineage: str) -> Any:
    from yoke_core.domain.deployment_run_candidate_containment import (
        candidate_contains_commit,
    )

    return candidate_contains_commit(
        conn,
        int(new_run["project_id"]),
        candidate_lineage=str(new_run["release_lineage"] or "").strip(),
        commit_sha=old_lineage,
    )


def _projection(conn: Any, old_id: str) -> Any:
    from yoke_core.domain.deployment_run_member_removal_read import read_removal

    return read_removal(conn, run_id=old_id, guard=False).projection


def read_takeover(
    conn: Any, new_run: Mapping[str, Any], old: Mapping[str, Any]
) -> TakeoverRead:
    """Ask the comparison and the shared groups before the older run's lock."""
    old_lineage = str(old["release_lineage"] or "")
    return TakeoverRead(
        old_lineage,
        _verdict(conn, new_run, old_lineage),
        _projection(conn, str(old["id"])),
    )


def current_takeover_read(
    conn: Any, read: TakeoverRead, new_run: Mapping[str, Any], old: dict[str, Any]
) -> TakeoverRead:
    """Confirm the unlocked read; never call the repository host under a lock."""
    from yoke_core.domain.deployment_run_target_takeover import TakeoverRefused

    old_id = str(old["id"])
    row = conn.execute(
        "SELECT release_lineage,status,current_stage,settling_at,superseded_by_run_id "
        "FROM deployment_runs WHERE id=%s",
        (old_id,),
    ).fetchone()
    if (
        row is None
        or str(row["release_lineage"] or "") != read.old_lineage
        or any(
            row[key] != old[key] for key in ("status", "current_stage", "settling_at")
        )
        or row["superseded_by_run_id"] is not None
        or not read.projection.holds(conn)
    ):
        raise TakeoverRefused(
            "takeover_inputs_changed",
            f"run {old_id} changed while takeover was prepared; no QA ownership "
            "was changed. Retry the same run creation request to read its current "
            "membership, QA and candidate containment before locking again.",
        )
    return read


def _not_contained_refusal(
    conn: Any, old: Mapping[str, Any], new_lineage: str, verdict: Any, moving: list
) -> str:
    from yoke_core.domain.deployment_run_target_takeover import has_shared_gates

    old_id = str(old["id"])
    detail = f" ({verdict.reason}: {verdict.recovery})" if verdict.reason else ""
    refs = [render_item_ref(conn, int(m["item_id"])) for m in moving]
    lines = [
        compose_refusal(
            f"run {old_id} on this flow and target is waiting only on item QA, and this candidate ({new_lineage or 'unpinned'}) is not known to contain its candidate ({old['release_lineage'] or 'unpinned'}){detail}. Taking it over would replace a build whose members this candidate may not carry, so nothing was created or changed.",
            recovery=f"create from a candidate that contains {old['release_lineage'] or 'the older run'}'s commit, or release its waiting members by hand:",
        ),
    ]
    if has_shared_gates(old["stages"]):
        lines.append(
            f"  {old_id} has run-level QA or approval holding every member, so "
            f"end it: yoke deployment-runs terminalize {old_id} --disposition "
            'cancelled --reason "<why>"; the next start enrolls ' + ", ".join(refs)
        )
    else:
        lines.extend(
            f'  yoke deployment-runs remove-item {old_id} {ref} --reason "<why>"'
            for ref in refs
        )
    return "\n".join(lines)


def require_contained(
    conn: Any,
    new_run: Mapping[str, Any],
    old: Mapping[str, Any],
    moving: list,
    verdict: Any = None,
) -> None:
    """Refuse, naming the members to release, unless *verdict* is contained.

    Without *verdict* the comparison is asked here.
    """
    from yoke_core.domain.deployment_run_target_takeover import (
        NOT_CONTAINED_CODE,
        TakeoverRefused,
    )

    if verdict is None:
        verdict = _verdict(conn, new_run, str(old["release_lineage"] or ""))
    if not verdict.contained:
        new_lineage = str(new_run["release_lineage"] or "").strip()
        raise TakeoverRefused(
            NOT_CONTAINED_CODE,
            _not_contained_refusal(conn, old, new_lineage, verdict, moving),
        )


__all__ = [
    "TakeoverRead",
    "current_takeover_read",
    "read_takeover",
    "require_contained",
]
