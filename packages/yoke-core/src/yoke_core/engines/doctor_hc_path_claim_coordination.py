"""Doctor HC for stale or empty coordination_only attestation rationale.

Two failure modes are flagged:

1. A ``path_claims`` row in ``state='blocked'`` whose ``blocked_reason``
   names a released upstream while at least one other non-terminal
   overlap on the same target survives. The blocked candidate should
   have been refreshed to point at the surviving upstream by the
   propagation surface — a stale ``blocked_reason`` indicates the
   refresh missed this row.
2. An ``item_dependencies`` row carrying ``gate_point='coordination_only'``
   whose ``rationale`` is NULL or empty whitespace. The agent-attested
   coordination edge must carry an authored rationale; an empty cell
   is a missing attestation.

``mode='exception'`` claims are SKIPPED — the operator-override path
is a sanctioned exception per AGENTS.md ``## Path Claims — Hard Rule``
and must not trigger an HC failure.

PASS when no rows match either failure mode; otherwise WARN with a
bounded enumeration of the affected claim / dependency ids.
"""

from __future__ import annotations

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-path-claim-coordination-rationale"
_HC_DESC = (
    "Path-claim coordination_only attestation rationale is missing, "
    "stale, or names a released upstream while overlap survives"
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _parse_upstream_claim_id(reason: str) -> int | None:
    """Parse ``path_claims.id=N`` out of ``blocked_reason``. Tolerant of
    trailing whitespace or alternative payloads — returns ``None`` when
    the prefix is absent or the suffix is not an integer.
    """
    if not reason:
        return None
    prefix = "path_claims.id="
    idx = reason.find(prefix)
    if idx < 0:
        return None
    tail = reason[idx + len(prefix):].strip()
    # Stop at the first non-digit so multi-clause reasons still parse.
    digits = []
    for ch in tail:
        if ch.isdigit():
            digits.append(ch)
        else:
            break
    if not digits:
        return None
    try:
        return int("".join(digits))
    except ValueError:
        return None


def _surviving_overlap_exists(
    conn, *, claim_id: int, upstream_id: int, integration_target: str,
) -> bool:
    p = _p(conn)
    target_rows = conn.execute(
        f"SELECT target_id FROM path_claim_targets WHERE claim_id = {p}",
        (claim_id,),
    ).fetchall()
    target_ids = [int(row[0]) for row in target_rows]
    if not target_ids:
        return False
    if _base._table_exists(conn, "path_targets"):
        from yoke_core.domain.path_claims_overlap import expand_lineage
        target_ids = expand_lineage(conn, target_ids)
    placeholders = ",".join(p for _ in target_ids)
    survivor = conn.execute(
        "SELECT 1 FROM path_claims other "
        "JOIN path_claim_targets ot ON ot.claim_id = other.id "
        f"WHERE other.id <> {p} "
        f"AND other.id <> {p} "
        f"AND other.integration_target = {p} "
        "AND other.state IN ('planned','blocked','active') "
        "AND other.mode <> 'exception' "
        f"AND ot.target_id IN ({placeholders}) "
        "LIMIT 1",
        (claim_id, upstream_id, integration_target, *target_ids),
    ).fetchone()
    return survivor is not None


def _flag_stale_blocked_reason(conn) -> list[str]:
    """Failure-mode 1: blocked rows naming a released upstream while
    another non-terminal overlap survives on the same target.

    Excludes ``mode='exception'`` rows (sanctioned operator override).
    """
    p = _p(conn)
    rows = query_rows(
        conn,
        "SELECT pc.id AS claim_id, pc.blocked_reason AS blocked_reason, "
        "pc.item_id AS item_id, pc.integration_target AS target "
        "FROM path_claims pc "
        "WHERE pc.state = 'blocked' "
        f"AND pc.blocked_reason LIKE {p} "
        "AND pc.mode <> 'exception'",
        ("%path_claims.id=%",),
    )
    flagged: list[str] = []
    for row in rows:
        claim_id = int(row["claim_id"])
        upstream_id = _parse_upstream_claim_id(str(row["blocked_reason"] or ""))
        if upstream_id is None:
            continue
        upstream = conn.execute(
            f"SELECT state FROM path_claims WHERE id = {p}",
            (upstream_id,),
        ).fetchone()
        if upstream is None:
            continue
        if str(upstream[0]) != "released":
            continue
        # Use lineage-aware overlap when path_targets is available so the HC
        # matches the door-lock classifier's ancestor/descendant semantics.
        if not _surviving_overlap_exists(
            conn,
            claim_id=claim_id,
            upstream_id=upstream_id,
            integration_target=str(row["target"]),
        ):
            continue
        flagged.append(
            f"path_claims.id={claim_id} item={row['item_id']} "
            f"target={row['target']} blocked_reason names released "
            f"upstream path_claims.id={upstream_id} while another overlap "
            f"survives"
        )
    return flagged


def _flag_empty_rationale(conn) -> list[str]:
    """Failure-mode 2: coordination_only edges with empty rationale."""
    rows = query_rows(
        conn,
        "SELECT id, dependent_item, blocking_item, rationale "
        "FROM item_dependencies "
        "WHERE gate_point = 'coordination_only' "
        "AND (rationale IS NULL OR TRIM(rationale) = '')",
    )
    flagged: list[str] = []
    for row in rows:
        flagged.append(
            f"item_dependencies.id={row['id']} "
            f"{row['dependent_item']} <-> {row['blocking_item']} "
            "carries empty rationale"
        )
    return flagged


def hc_path_claim_coordination_rationale(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """Flag stale-or-empty coordination-only attestation evidence."""
    if not _base._table_exists(conn, "path_claims"):
        rec.record(_HC_NAME, _HC_DESC, "PASS", "path_claims missing — skipping")
        return
    if not _base._table_exists(conn, "path_claim_targets"):
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            "path_claim_targets missing — skipping",
        )
        return
    if not _base._table_exists(conn, "item_dependencies"):
        # Failure-mode 2 needs item_dependencies; still try failure-mode 1.
        stale = _flag_stale_blocked_reason(conn)
        empty: list[str] = []
    else:
        stale = _flag_stale_blocked_reason(conn)
        empty = _flag_empty_rationale(conn)

    if not stale and not empty:
        rec.record(_HC_NAME, _HC_DESC, "PASS", "")
        return

    issues: list[str] = []
    if stale:
        issues.append(
            f"- {len(stale)} blocked path_claim(s) naming a released "
            "upstream while another non-terminal overlap survives on the "
            "same target. The propagation refresh missed these rows."
        )
        for line in stale[:10]:
            issues.append(f"  - {line}")
        if len(stale) > 10:
            issues.append(f"  - ... and {len(stale) - 10} more")
    if empty:
        issues.append(
            f"- {len(empty)} coordination_only item_dependencies "
            "row(s) with NULL or empty rationale. Each coordination edge "
            "must carry an authored agent-attestation."
        )
        for line in empty[:10]:
            issues.append(f"  - {line}")
        if len(empty) > 10:
            issues.append(f"  - ... and {len(empty) - 10} more")

    rec.record(_HC_NAME, _HC_DESC, "WARN", "\n".join(issues))


__all__ = ["hc_path_claim_coordination_rationale"]
