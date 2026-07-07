"""Spec-vs-claim coverage gate.

Detects drift between an item's File Budget (authored in the spec body)
and the paths actually covered by its active path_claims rows.

The failure mode this catches: refine pass after upstream blockers
release does not always widen the downstream claim onto deferred files.
The spec body promises coverage, the claim does not deliver, and
implementation lands files outside declared coverage.

Run as a hard-block gate at advance preflight (target=implementing) or
ad hoc via the CLI ``__main__``.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from typing import Any, List, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.file_budget_paths import (
    extract_file_budget_paths,
)
from yoke_core.domain.schema_common import (
    _connect_raw,
    _get_columns as _schema_get_columns,
    _table_exists as _schema_table_exists,
)

_NON_TERMINAL_CLAIM_STATES = ("planned", "active", "blocked")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


@dataclass
class CoverageResult:
    """Outcome of comparing File Budget paths to claim coverage.

    Attributes:
        item_id: The item evaluated.
        is_blocked: True when ``missing_paths`` is non-empty.
        file_budget_paths: All path-shaped tokens extracted from the
            ``## File Budget`` section.
        claim_paths: Union of declared paths across the item's active,
            planned, and blocked path_claims rows.
        missing_paths: ``file_budget_paths - claim_paths``, sorted.
        active_claim_ids: Non-terminal claim ids contributing coverage.
        no_claims: True when the item has no non-terminal claim rows.
    """

    item_id: int
    is_blocked: bool
    file_budget_paths: List[str] = field(default_factory=list)
    claim_paths: List[str] = field(default_factory=list)
    missing_paths: List[str] = field(default_factory=list)
    active_claim_ids: List[int] = field(default_factory=list)
    no_claims: bool = False

    def to_dict(self) -> dict:
        return {
            "item_id": self.item_id,
            "is_blocked": self.is_blocked,
            "file_budget_paths": list(self.file_budget_paths),
            "claim_paths": list(self.claim_paths),
            "missing_paths": list(self.missing_paths),
            "active_claim_ids": list(self.active_claim_ids),
            "no_claims": self.no_claims,
        }


def _read_spec_text(conn: Any, item_id: int) -> str:
    """Read the item's spec content, probing both storage layouts.

    The production ``items`` table carries a ``spec`` column (added by
    migration); minimal in-memory test fixtures only define
    ``create_core_tables`` and store spec rows in ``item_sections``.
    This helper handles both — prefer the ``items.spec`` column when
    present, fall back to the ``item_sections`` row, and finally to a
    body-section for legacy items.
    """
    columns = set(_schema_get_columns(conn, "items"))
    marker = _p(conn)
    if "spec" in columns:
        row = conn.execute(
            f"SELECT spec FROM items WHERE id = {marker}", (item_id,),
        ).fetchone()
        if row is not None:
            text = row["spec"] if hasattr(row, "keys") else row[0]
            if text:
                return text
    if not _schema_table_exists(conn, "item_sections"):
        return ""
    for section_name in ("spec", "body"):
        row = conn.execute(
            "SELECT COALESCE(content, '') AS content FROM item_sections "
            f"WHERE item_id = {marker} AND section_name = {marker}",
            (item_id, section_name),
        ).fetchone()
        if row is None:
            continue
        text = row["content"] if hasattr(row, "keys") else row[0]
        if text:
            return text
    return ""


def _active_claim_coverage(
    conn: Any, item_id: int,
) -> tuple[List[int], List[str]]:
    """Return (claim_ids, declared_paths) for non-terminal claims."""
    marker = _p(conn)
    placeholders = ",".join(marker for _ in _NON_TERMINAL_CLAIM_STATES)
    claim_rows = conn.execute(
        f"SELECT id FROM path_claims WHERE item_id = {marker} "
        f"AND state IN ({placeholders}) ORDER BY id",
        (item_id, *_NON_TERMINAL_CLAIM_STATES),
    ).fetchall()
    claim_ids = [int(r["id"] if hasattr(r, "keys") else r[0])
                 for r in claim_rows]
    if not claim_ids:
        return [], []
    target_placeholders = ",".join(marker for _ in claim_ids)
    target_rows = conn.execute(
        f"SELECT DISTINCT pt.path_string "
        f"FROM path_claim_targets pct "
        f"JOIN path_targets pt ON pt.id = pct.target_id "
        f"WHERE pct.claim_id IN ({target_placeholders}) "
        f"ORDER BY pt.path_string",
        tuple(claim_ids),
    ).fetchall()
    paths = [r["path_string"] if hasattr(r, "keys") else r[0]
             for r in target_rows]
    return claim_ids, paths


def evaluate(
    item_id: int,
    *,
    conn: Any | None = None,
) -> CoverageResult:
    """Block when File Budget promises coverage the active claim lacks.

    A no-op when:
    - the item has no spec body,
    - the spec has no ``## File Budget`` section,
    - the File Budget section lists no path-shaped tokens, or
    - the item has no non-terminal claim rows (``no_claims=True`` —
      handled by the existing path-claim-required gate, not here).

    Returns a populated :class:`CoverageResult` even on the pass path so
    callers can log the comparison.
    """
    own_conn = conn is None
    if conn is None:
        conn = _connect_raw()
    try:
        spec = _read_spec_text(conn, item_id)
        budget_paths = extract_file_budget_paths(spec)
        if not budget_paths:
            return CoverageResult(
                item_id=item_id,
                is_blocked=False,
                file_budget_paths=budget_paths,
            )
        claim_ids, claim_paths = _active_claim_coverage(conn, item_id)
    finally:
        if own_conn:
            conn.close()

    if not claim_ids:
        return CoverageResult(
            item_id=item_id,
            is_blocked=False,
            file_budget_paths=budget_paths,
            claim_paths=[],
            missing_paths=[],
            active_claim_ids=[],
            no_claims=True,
        )

    claim_set = set(claim_paths)
    missing = sorted(p for p in budget_paths if p not in claim_set)
    return CoverageResult(
        item_id=item_id,
        is_blocked=bool(missing),
        file_budget_paths=budget_paths,
        claim_paths=claim_paths,
        missing_paths=missing,
        active_claim_ids=claim_ids,
        no_claims=False,
    )


def _format_block_message(result: CoverageResult) -> str:
    lines = [
        f"BLOCKED: YOK-{result.item_id} File Budget lists "
        f"{len(result.missing_paths)} path(s) not covered by any "
        f"active path_claim.",
        "",
        "Missing:",
    ]
    for p in result.missing_paths:
        lines.append(f"  - {p}")
    lines.append("")
    lines.append("Active claim coverage:")
    for p in result.claim_paths:
        lines.append(f"  - {p}")
    lines.append("")
    if result.active_claim_ids:
        target_id = result.active_claim_ids[0]
        added = ",".join(result.missing_paths)
        lines.append(
            "Remediation: widen the active claim onto the missing paths, "
            "for example:"
        )
        lines.append(
            f"  python3 -m yoke_core.api.service_client path-claim-widen "
            f"{target_id} --paths \"{added}\" "
            f"--reason \"...\" [--allow-planned]"
        )
        lines.append(
            "Use --allow-planned when the file does not yet exist on "
            "the integration target."
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="path-claim-spec-coverage-gate",
        description=(
            "Block when ## File Budget promises paths the item's active "
            "claim does not cover."
        ),
    )
    parser.add_argument("item_id", help="Item id (bare integer or YOK-N)")
    parser.add_argument(
        "--json", action="store_true",
        help="Emit JSON instead of human-readable text.",
    )
    args = parser.parse_args(argv)

    raw = args.item_id
    if isinstance(raw, str) and raw.upper().startswith("YOK-"):
        raw = raw.split("-", 1)[1]
    try:
        item_id = int(raw)
    except (TypeError, ValueError):
        print(f"ERROR: cannot parse item id '{args.item_id}'",
              file=sys.stderr)
        return 2

    result = evaluate(item_id)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    elif result.is_blocked:
        print(_format_block_message(result), file=sys.stderr)
    else:
        print(
            f"OK: YOK-{result.item_id} File Budget coverage matches "
            f"active claims ({len(result.file_budget_paths)} path(s) "
            f"checked)."
        )
    return 1 if result.is_blocked else 0


__all__ = [
    "CoverageResult",
    "evaluate",
    "extract_file_budget_paths",
    "main",
]


if __name__ == "__main__":
    sys.exit(main())
