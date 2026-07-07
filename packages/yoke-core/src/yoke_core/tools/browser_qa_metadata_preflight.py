"""Verify every non-terminal item carries populated browser_qa_metadata.

Runs during the residue-removal commit to guarantee that no live caller
will encounter ``NULL``, ``''``, or literal ``'null'`` metadata once the
regex fallback is gone. Exits 0 when every non-terminal row has a valid
object; exits non-zero and prints the offending rows otherwise.

CLI usage::

    python3 -m yoke_core.tools.browser_qa_metadata_preflight

Exit codes:
    0 — every non-terminal item has valid metadata
    1 — at least one non-terminal item has unset/invalid metadata
    2 — CLI usage error
"""

from __future__ import annotations

import argparse
import sys
from typing import Iterable, List, Optional, Sequence

from yoke_core.domain.browser_qa_metadata import (
    BrowserQaMetadataError,
    validate_json_string,
)
from yoke_core.domain.db_helpers import connect, query_rows
from yoke_core.domain.lifecycle import (
    EXCEPTIONAL,
    TERMINAL_FAILURE,
    TERMINAL_SUCCESS,
)


def _terminal_statuses() -> List[str]:
    """Statuses that exempt an item from the metadata requirement.

    Terminal success ``done``, terminal failure ``stopped``/``failed``, and
    the pre-lifecycle ``cancelled`` state all belong here — those items are
    either shipped or stopped, and the classifier delete does not affect
    them. ``blocked`` is deliberately NOT exempt: blocked items may
    eventually be unblocked and re-enter the seeding path.
    """
    return sorted({*TERMINAL_SUCCESS, *TERMINAL_FAILURE, "cancelled"})


def _non_terminal_where(col: str = "status") -> tuple[str, tuple]:
    terminals = _terminal_statuses()
    placeholders = ",".join(["%s"] * len(terminals))
    return f"{col} NOT IN ({placeholders})", tuple(terminals)


def find_unset_rows(db_path: Optional[str] = None) -> List[dict]:
    """Return the list of non-terminal items with missing/invalid metadata."""
    conn = connect(db_path)
    try:
        where, params = _non_terminal_where()
        rows = query_rows(
            conn,
            f"SELECT id, status, title, COALESCE(browser_qa_metadata, '') AS metadata "
            f"FROM items WHERE {where} ORDER BY id",
            params,
        )
    finally:
        conn.close()

    unset: List[dict] = []
    for row in rows:
        raw = row["metadata"]
        if raw is None or raw == "" or raw == "null":
            unset.append({
                "id": int(row["id"]),
                "status": str(row["status"]),
                "title": str(row["title"]),
                "reason": "missing",
            })
            continue
        try:
            validate_json_string(raw)
        except BrowserQaMetadataError as exc:
            unset.append({
                "id": int(row["id"]),
                "status": str(row["status"]),
                "title": str(row["title"]),
                "reason": f"invalid: {exc}",
            })
    return unset


def _format_findings(unset: Sequence[dict]) -> str:
    lines = [
        f"YOK-{row['id']} ({row['status']}): {row['title']} — {row['reason']}"
        for row in unset
    ]
    return "\n".join(lines)


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.tools.browser_qa_metadata_preflight",
        description=(
            "Verify every non-terminal item has a populated browser_qa_metadata object."
        ),
    )
    parser.add_argument(
        "--db",
        default=None,
        help="Override the legacy DB token (defaults to selected authority).",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    findings = find_unset_rows(db_path=args.db)
    if not findings:
        print("browser_qa_metadata preflight: all non-terminal items are populated.")
        return 0

    print(
        f"browser_qa_metadata preflight: {len(findings)} non-terminal item(s) "
        "are missing or have invalid metadata. Classifier delete is BLOCKED.",
        file=sys.stderr,
    )
    print(_format_findings(findings), file=sys.stderr)
    return 1


# Expose the exceptional-state constant so callers can extend the exemption list.
_EXCEPTIONAL_REFERENCE = EXCEPTIONAL


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
