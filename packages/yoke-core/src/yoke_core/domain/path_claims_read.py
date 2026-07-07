"""Read-only projections for path claims and cross-claim conflicts."""

from __future__ import annotations

from typing import Any, Iterable, List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.path_claims import get_claim
from yoke_core.domain.path_claims_overlap import (
    classify_overlap,
    expand_lineage,
)


_NON_TERMINAL_STATES = ("planned", "blocked", "active")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _path_strings_for(
    conn: Any, target_ids: Iterable[int]
) -> List[str]:
    """Resolve target ids to readable project-relative paths."""
    cache = {}
    out: List[str] = []
    ids = list(target_ids)
    if not ids:
        return out
    placeholders = ",".join(_p(conn) for _ in ids)
    rows = conn.execute(
        f"SELECT id, path_string FROM path_targets WHERE id IN ({placeholders})",
        tuple(ids),
    ).fetchall()
    for row in rows:
        cache[int(row[0])] = str(row[1])
    for tid in ids:
        out.append(cache.get(int(tid), f"<unknown target {tid}>"))
    return out


def _target_details_for(
    conn: Any, target_ids: Iterable[int]
) -> List[dict]:
    """Resolve target ids to dicts for dispatch JSON and body rendering."""
    ids = list(target_ids)
    if not ids:
        return []
    placeholders = ",".join(_p(conn) for _ in ids)
    rows = conn.execute(
        "SELECT id, path_string, kind, materialization_state "
        f"FROM path_targets WHERE id IN ({placeholders})",
        tuple(ids),
    ).fetchall()
    cache = {
        int(row[0]): {
            "target_id": int(row[0]),
            "path_string": str(row[1]),
            "kind": str(row[2]),
            "materialization_state": str(row[3]),
        }
        for row in rows
    }
    out: List[dict] = []
    for tid in ids:
        out.append(
            cache.get(int(tid), {
                "target_id": int(tid),
                "path_string": f"<unknown target {tid}>",
                "kind": "unknown",
                "materialization_state": "unknown",
            })
        )
    return out


def _amendments_for(
    conn: Any, claim_id: int
) -> List[dict]:
    """Return the amendment history for one claim, oldest first."""
    p = _p(conn)
    rows = conn.execute(
        "SELECT id, amendment_kind, payload, reason, amended_at "
        "FROM path_claim_amendments "
        f"WHERE claim_id = {p} ORDER BY id",
        (claim_id,),
    ).fetchall()
    return [
        {
            "id": int(r[0]),
            "amendment_kind": str(r[1]),
            "payload": r[2],
            "reason": r[3],
            "amended_at": r[4],
        }
        for r in rows
    ]


def _blocking_conflicts_for(
    conn: Any,
    claim_id: int,
    *,
    state: str,
    integration_target: str,
    target_ids: List[int],
) -> List[dict]:
    """Identify other non-terminal claims that conflict with this one."""
    if state not in _NON_TERMINAL_STATES or not target_ids:
        return []
    expanded_targets = expand_lineage(conn, target_ids)
    p = _p(conn)
    placeholders = ",".join(p for _ in expanded_targets)
    state_placeholders = ",".join(p for _ in _NON_TERMINAL_STATES)
    candidates = conn.execute(
        f"SELECT pc.id, pc.state FROM path_claims pc "
        f"WHERE pc.integration_target = {p} "
        f"  AND pc.state IN ({state_placeholders}) "
        f"  AND pc.mode <> 'exception' "
        f"  AND pc.id <> {p} "
        f"  AND EXISTS ("
        f"    SELECT 1 FROM path_claim_targets pct "
        f"    WHERE pct.claim_id = pc.id AND pct.target_id IN ({placeholders})"
        f"  ) "
        f"ORDER BY pc.id",
        (
            integration_target,
            *_NON_TERMINAL_STATES,
            claim_id,
            *expanded_targets,
        ),
    ).fetchall()
    out: List[dict] = []
    expanded_set = set(expanded_targets)
    for cand_id, cand_state in candidates:
        if state != "blocked" and _pair_is_serial(
            conn, claim_id=claim_id, blocking_claim_id=int(cand_id),
        ):
            continue
        overlap_ids = [
            int(r[0])
            for r in conn.execute(
                f"SELECT target_id FROM path_claim_targets "
                f"WHERE claim_id = {p} AND target_id IN ({placeholders}) "
                "ORDER BY target_id",
                (int(cand_id), *expanded_targets),
            )
        ]
        if not overlap_ids:
            continue
        out.append(
            {
                "claim_id": int(cand_id),
                "state": str(cand_state),
                "blocking_target_ids": overlap_ids,
                "blocking_paths": _path_strings_for(conn, overlap_ids),
            }
        )
        assert set(overlap_ids).issubset(expanded_set)
    return out


def _pair_is_serial(
    conn: Any, *, claim_id: int, blocking_claim_id: int,
) -> bool:
    """Return True when the pair is ordered by dep graph or override."""
    from yoke_core.domain.path_claims_dependency_resolver import (
        has_bidirectional_dep_edge,
    )
    from yoke_core.domain.path_claims_override import is_active_override

    if has_bidirectional_dep_edge(
        conn,
        candidate_claim_id=claim_id,
        candidate_item_id=None,
        blocking_claim_id=blocking_claim_id,
    ):
        return True
    return is_active_override(
        conn,
        path_claim_id=claim_id,
        blocking_claim_id=blocking_claim_id,
    )


def claim_projection(
    conn: Any, claim_id: int
) -> dict:
    """Return the rich, agent-readable projection for one claim."""
    base = get_claim(conn, claim_id)
    target_ids = [int(t) for t in base.get("target_ids") or []]
    paths = _path_strings_for(conn, target_ids)
    target_details = _target_details_for(conn, target_ids)
    amendments = _amendments_for(conn, claim_id)
    conflicts = _blocking_conflicts_for(
        conn,
        claim_id,
        state=str(base["state"]),
        integration_target=str(base["integration_target"]),
        target_ids=target_ids,
    )
    return {
        **base,
        "declared_paths": paths,
        "declared_targets": target_details,
        "amendments": amendments,
        "blocking_conflicts": conflicts,
    }


def item_view(
    conn: Any,
    item_id: int,
    *,
    states: Optional[Iterable[str]] = None,
) -> List[dict]:
    """Return rich projections for every claim attached to an item.

    Optional ``states`` filter accepts any subset of
    ``planned`` / ``blocked`` / ``active`` / ``released`` / ``cancelled``.
    Defaults to "all states" so a cold-start agent sees the full
    history without per-call filtering.
    """
    state_filter = list(states) if states else []
    p = _p(conn)
    if state_filter:
        placeholders = ",".join(p for _ in state_filter)
        rows = conn.execute(
            f"SELECT id FROM path_claims "
            f"WHERE item_id = {p} AND state IN ({placeholders}) "
            "ORDER BY id",
            (item_id, *state_filter),
        ).fetchall()
    else:
        rows = conn.execute(
            f"SELECT id FROM path_claims WHERE item_id = {p} ORDER BY id",
            (item_id,),
        ).fetchall()
    return [claim_projection(conn, int(r[0])) for r in rows]


def cross_claim_conflicts(
    conn: Any,
    *,
    integration_target: Optional[str] = None,
) -> List[dict]:
    """Return every active conflict pair across the open claim frontier.

    Each conflict surfaces both participants by id and state, the
    integration target they share, the canonical blocking target ids,
    the readable blocking paths, and a recommended remediation hint.

    The classifier from :mod:`path_claims_overlap` decides whether a
    given pair is incompatible or serial-via-dependency; only
    incompatible pairs surface. Pairs are deduplicated so each
    ``(left, right)`` overlap is reported once.
    """
    where = ""
    params: list = list(_NON_TERMINAL_STATES)
    p = _p(conn)
    state_placeholders = ",".join(p for _ in _NON_TERMINAL_STATES)
    if integration_target is not None:
        where = f"AND integration_target = {p} "
        params.append(integration_target)
    rows = conn.execute(
        f"SELECT id, integration_target, state FROM path_claims "
        f"WHERE state IN ({state_placeholders}) {where}"
        f"ORDER BY id",
        tuple(params),
    ).fetchall()
    seen_pairs: set[tuple[int, int]] = set()
    out: List[dict] = []
    for row in rows:
        claim_id = int(row[0])
        target = str(row[1])
        target_ids = [
            int(t[0])
            for t in conn.execute(
                "SELECT target_id FROM path_claim_targets "
                f"WHERE claim_id = {p} ORDER BY target_id",
                (claim_id,),
            )
        ]
        if not target_ids:
            continue
        classification = classify_overlap(
            conn,
            target_ids=target_ids,
            integration_target=target,
            exclude_claim_id=claim_id,
            phase="register",
        )
        from yoke_core.domain.path_claims_overlap import OverlapClassification

        if classification is not OverlapClassification.INCOMPATIBLE:
            continue
        for other in _blocking_conflicts_for(
            conn,
            claim_id,
            state=str(row[2]),
            integration_target=target,
            target_ids=target_ids,
        ):
            other_id = int(other["claim_id"])
            pair = tuple(sorted((claim_id, other_id)))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            out.append(
                {
                    "integration_target": target,
                    "claim_a": {
                        "claim_id": claim_id,
                        "state": str(row[2]),
                    },
                    "claim_b": {
                        "claim_id": other_id,
                        "state": other["state"],
                    },
                    "blocking_target_ids": other["blocking_target_ids"],
                    "blocking_paths": other["blocking_paths"],
                    "recommended_remediation": (
                        "amend one claim's coverage to drop the overlapping "
                        "path target(s), declare a serial-via-dependency "
                        "upstream, or release/cancel the older claim before "
                        "activating the newer one"
                    ),
                }
            )
    return out


__all__ = ["claim_projection", "cross_claim_conflicts", "item_view"]
