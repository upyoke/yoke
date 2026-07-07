"""Doctor HC for missing canonical coverage on symlink-claimed paths.

Per-claim invariant: when a non-terminal path-claim covers an in-repo
symlink-source recorded by the latest project snapshot, it must also
cover the symlink's canonical target. This is a backstop for
registration-time canonicalization in :mod:`path_claims_resolve` — if
a row slips past the helper, the HC flags the gap.

PASS when every non-terminal claim's symlink-source coverage includes
its canonical target. WARN with a bounded enumeration otherwise.
"""

from __future__ import annotations

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.path_claims_symlink_expansion import (
    SYMLINK_CANONICALIZED,
)

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-path-claim-symlink-coverage"
_HC_DESC = (
    "Path-claim covers an in-repo symlink without its canonical target"
)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _value(row, key: str, index: int):
    return row[key] if hasattr(row, "keys") else row[index]


def _canonical_pairs_by_project(conn) -> dict[tuple[int, str], str]:
    p = _p(conn)
    rows = query_rows(
        conn,
        "SELECT s.project_id, f.symlink_path, f.canonical_path "
        "FROM path_snapshot_symlink_facts f "
        "JOIN path_snapshots s ON s.id = f.snapshot_id "
        f"WHERE f.reason = {p} "
        "AND f.canonical_path IS NOT NULL "
        "AND s.id = ("
        "  SELECT MAX(s2.id) FROM path_snapshots s2 "
        "  WHERE s2.project_id = s.project_id"
        ")",
        (SYMLINK_CANONICALIZED,),
    )
    pairs: dict[tuple[int, str], str] = {}
    for row in rows:
        pairs[(
            int(_value(row, "project_id", 0)),
            str(_value(row, "symlink_path", 1)),
        )] = str(_value(row, "canonical_path", 2))
    return pairs


def _flag_claims(conn) -> list[str]:
    canonical_by_path = _canonical_pairs_by_project(conn)
    rows = query_rows(
        conn,
        "SELECT pc.id AS claim_id, pc.item_id AS item_id, "
        "p.id AS project_id, p.slug AS project, pc.state AS state, "
        "pc.integration_target AS target "
        "FROM path_claims pc "
        "LEFT JOIN items i ON i.id = pc.item_id "
        "LEFT JOIN projects p ON p.id = i.project_id "
        "WHERE pc.state IN ('planned','blocked','active') "
        "AND pc.mode <> 'exception'",
    )
    claim_ids = [
        int(_value(row, "claim_id", 0))
        for row in rows
    ]
    paths_by_claim: dict[int, set[str]] = {claim_id: set() for claim_id in claim_ids}
    if claim_ids:
        p = _p(conn)
        placeholders = ",".join(p for _ in claim_ids)
        target_rows = query_rows(
            conn,
            "SELECT pct.claim_id, t.path_string "
            "FROM path_claim_targets pct "
            "JOIN path_targets t ON t.id = pct.target_id "
            f"WHERE pct.claim_id IN ({placeholders})",
            tuple(claim_ids),
        )
        for target_row in target_rows:
            claim_id = int(_value(target_row, "claim_id", 0))
            path = _value(target_row, "path_string", 1)
            paths_by_claim.setdefault(claim_id, set()).add(str(path))
    flagged: list[str] = []
    for row in rows:
        project_id = _value(row, "project_id", 2)
        if project_id is None:
            continue
        claim_id = int(_value(row, "claim_id", 0))
        item_id = _value(row, "item_id", 1)
        item_ref = f"YOK-{item_id}" if item_id is not None else "<item-ref>"
        covered = paths_by_claim.get(claim_id, set())
        for covered_path in sorted(covered):
            canonical = canonical_by_path.get((int(project_id), covered_path))
            if canonical and canonical not in covered:
                flagged.append(
                    f"path_claims.id={claim_id} item={item_id} "
                    f"covers symlink '{covered_path}' (-> '{canonical}') "
                    f"without canonical coverage; widen via "
                    f"`yoke claims path widen --claim-id {claim_id} "
                    f"--add-paths {canonical} --reason "
                    "'cover symlink canonical target' --item "
                    f"{item_ref}`"
                )
    return flagged


def hc_path_claim_symlink_coverage(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """Flag non-terminal claims whose symlink coverage omits the canonical."""
    if not _base._table_exists(conn, "path_claims"):
        rec.record(_HC_NAME, _HC_DESC, "PASS", "path_claims missing — skipping")
        return
    if not _base._table_exists(conn, "path_claim_targets"):
        rec.record(_HC_NAME, _HC_DESC, "PASS", "path_claim_targets missing — skipping")
        return
    if not _base._table_exists(conn, "path_targets"):
        rec.record(_HC_NAME, _HC_DESC, "PASS", "path_targets missing — skipping")
        return
    if not _base._table_exists(conn, "path_snapshots"):
        rec.record(_HC_NAME, _HC_DESC, "PASS", "path_snapshots missing — skipping")
        return
    if not _base._table_exists(conn, "path_snapshot_symlink_facts"):
        rec.record(
            _HC_NAME, _HC_DESC, "PASS",
            "path_snapshot_symlink_facts missing — skipping",
        )
        return
    flagged = _flag_claims(conn)
    if not flagged:
        rec.record(_HC_NAME, _HC_DESC, "PASS", "")
        return
    issues: list[str] = []
    issues.append(
        f"- {len(flagged)} claim(s) cover a symlink-source without "
        "its canonical target. Each row below names the symlink + "
        "canonical pair and the widen command to fix:"
    )
    for line in flagged[:10]:
        issues.append(f"  - {line}")
    if len(flagged) > 10:
        issues.append(f"  - ... and {len(flagged) - 10} more")
    rec.record(_HC_NAME, _HC_DESC, "WARN", "\n".join(issues))


__all__ = ["hc_path_claim_symlink_coverage"]
