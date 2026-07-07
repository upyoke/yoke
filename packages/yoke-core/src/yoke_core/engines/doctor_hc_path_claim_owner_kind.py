"""HC-path-claim-owner-kind: surface invalid or missing typed ownership.

Scans non-terminal ``path_claims`` rows for owner-typing problems that
the typed-ownership contract requires:

- ``owner_kind IS NULL`` on a non-terminal row (planned/blocked/active)
  — the row predates the migration backfill or the migration could
  not classify it (contradictory legacy signals).
- ``owner_kind`` set but the required typed field is NULL or mismatches
  the legacy column (for example ``owner_kind='item'`` with NULL
  ``owner_item_id``).
- ``owner_kind`` value not in the closed enum (``item`` / ``session`` /
  ``process``).
- Item-owned row whose ``owner_item_id`` references a non-existent
  ``items.id`` (dangling reference; the column is intentionally not
  FK-constrained to match the legacy ``item_id`` column behavior in
  test fixtures, so the HC catches integrity).

Read-only. Self-skips cleanly on minimal-schema fixtures when
``path_claims`` is missing or lacks the typed owner columns.

Remediation pointers:
- ``python3 -m yoke_core.domain.migration_apply rehearse YOK-N``
  followed by ``live-apply`` re-runs the backfill module.
- Contradictory rows surface their row id, state, and legacy
  signals so the operator can null one of the mutually exclusive
  legacy columns before re-running the backfill.
"""

from __future__ import annotations

from typing import List

import yoke_core.engines.doctor_report as _base
from yoke_core.domain import db_backend
from yoke_core.domain.path_claim_owner import VALID_OWNER_KINDS
from yoke_core.domain.schema_common import _get_columns as _schema_get_columns
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-path-claim-owner-kind"
_HC_DESC = (
    "Non-terminal path_claims rows with missing, invalid, or "
    "contradictory typed ownership"
)
_LIST_PREVIEW = 10


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _table_has_typed_owner(conn) -> bool:
    try:
        cols = set(_schema_get_columns(conn, "path_claims"))
    except Exception:
        return False
    return {"owner_kind", "owner_item_id", "owner_session_id",
            "owner_work_claim_id"}.issubset(cols)


def hc_path_claim_owner_kind(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    """Report path_claims rows whose typed ownership is broken or missing."""
    if not _base._table_exists(conn, "path_claims"):
        rec.record(_HC_NAME, _HC_DESC, "PASS",
                   "path_claims table missing — skipping")
        return
    if not _table_has_typed_owner(conn):
        rec.record(_HC_NAME, _HC_DESC, "SKIP",
                   "typed owner columns absent — pre-migration schema; "
                   "run migration_apply rehearse + live-apply for "
                   "path_claim_owner_kind")
        return

    issues: List[str] = []

    # 1) NULL owner_kind on non-terminal rows.
    null_rows = conn.execute(
        "SELECT id, state, item_id, work_claim_id, session_id "
        "FROM path_claims "
        "WHERE owner_kind IS NULL AND state IN ('planned','blocked','active') "
        "ORDER BY id"
    ).fetchall()
    if null_rows:
        issues.append(
            f"- {len(null_rows)} non-terminal path_claims row(s) lack "
            "owner_kind. The backfill could not classify them — most "
            "likely both item_id AND work_claim_id are set (contradictory)."
        )
        for row in null_rows[:_LIST_PREVIEW]:
            issues.append(
                f"  - id={row[0]} state={row[1]} item_id={row[2]} "
                f"work_claim_id={row[3]} session_id={row[4]}"
            )
        if len(null_rows) > _LIST_PREVIEW:
            issues.append(
                f"  ... and {len(null_rows) - _LIST_PREVIEW} more"
            )

    # 2) owner_kind not in the closed enum.
    p = _p(conn)
    placeholders = ",".join(p for _ in VALID_OWNER_KINDS)
    bad_kind_rows = conn.execute(
        f"SELECT id, owner_kind, state FROM path_claims "
        f"WHERE owner_kind IS NOT NULL "
        f"AND owner_kind NOT IN ({placeholders}) "
        f"ORDER BY id",
        tuple(VALID_OWNER_KINDS),
    ).fetchall()
    if bad_kind_rows:
        issues.append(
            f"- {len(bad_kind_rows)} path_claims row(s) carry an "
            f"owner_kind outside the closed enum "
            f"{VALID_OWNER_KINDS!r}."
        )
        for row in bad_kind_rows[:_LIST_PREVIEW]:
            issues.append(
                f"  - id={row[0]} owner_kind={row[1]!r} state={row[2]}"
            )

    # 3) Owner kind set but required typed field missing.
    missing_field_rows = conn.execute(
        "SELECT id, owner_kind, owner_item_id, owner_session_id, "
        "owner_work_claim_id, state "
        "FROM path_claims "
        "WHERE state IN ('planned','blocked','active') AND ("
        "  (owner_kind='item'    AND owner_item_id IS NULL) OR "
        "  (owner_kind='session' AND owner_session_id IS NULL) OR "
        "  (owner_kind='process' AND owner_work_claim_id IS NULL)"
        ") ORDER BY id"
    ).fetchall()
    if missing_field_rows:
        issues.append(
            f"- {len(missing_field_rows)} non-terminal path_claims row(s) "
            "declare an owner_kind but lack the matching typed owner "
            "field (item/session/process)."
        )
        for row in missing_field_rows[:_LIST_PREVIEW]:
            issues.append(
                f"  - id={row[0]} owner_kind={row[1]!r} "
                f"owner_item_id={row[2]} owner_session_id={row[3]} "
                f"owner_work_claim_id={row[4]} state={row[5]}"
            )

    # 4) Off-axis owner fields populated alongside a different kind.
    off_axis_rows = conn.execute(
        "SELECT id, owner_kind, owner_item_id, owner_session_id, "
        "owner_work_claim_id "
        "FROM path_claims "
        "WHERE owner_kind IS NOT NULL AND ("
        "  (owner_kind='item' AND ("
        "    owner_session_id IS NOT NULL OR owner_work_claim_id IS NOT NULL"
        "  )) OR "
        "  (owner_kind='session' AND ("
        "    owner_item_id IS NOT NULL OR owner_work_claim_id IS NOT NULL"
        "  )) OR "
        "  (owner_kind='process' AND ("
        "    owner_item_id IS NOT NULL OR owner_session_id IS NOT NULL"
        "  ))"
        ") ORDER BY id"
    ).fetchall()
    if off_axis_rows:
        issues.append(
            f"- {len(off_axis_rows)} path_claims row(s) populate an "
            "off-axis owner field that contradicts owner_kind."
        )
        for row in off_axis_rows[:_LIST_PREVIEW]:
            issues.append(
                f"  - id={row[0]} owner_kind={row[1]!r} "
                f"owner_item_id={row[2]} owner_session_id={row[3]} "
                f"owner_work_claim_id={row[4]}"
            )

    # 5) Item-owned dangling reference (only when items table is present).
    if _base._table_exists(conn, "items"):
        dangling_rows = conn.execute(
            "SELECT pc.id, pc.owner_item_id, pc.state "
            "FROM path_claims pc "
            "LEFT JOIN items i ON i.id = pc.owner_item_id "
            "WHERE pc.owner_kind='item' "
            "AND pc.owner_item_id IS NOT NULL "
            "AND i.id IS NULL "
            "AND pc.state IN ('planned','blocked','active') "
            "ORDER BY pc.id"
        ).fetchall()
        if dangling_rows:
            issues.append(
                f"- {len(dangling_rows)} item-owned path_claims row(s) "
                "reference a non-existent items.id (dangling)."
            )
            for row in dangling_rows[:_LIST_PREVIEW]:
                issues.append(
                    f"  - id={row[0]} owner_item_id={row[1]} state={row[2]}"
                )

    if not issues:
        rec.record(_HC_NAME, _HC_DESC, "PASS", "")
        return

    issues.append(
        "- Rerun the backfill via `python3 -m yoke_core.domain."
        "migration_apply rehearse YOK-N` then `live-apply YOK-N` after "
        "resolving contradictory legacy signals (typically: null one of "
        "item_id / work_claim_id on the offending rows)."
    )
    rec.record(_HC_NAME, _HC_DESC, "WARN", "\n".join(issues))


__all__ = ["hc_path_claim_owner_kind"]
