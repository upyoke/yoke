"""Discovery scan helper for done-transition gates."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from yoke_core.domain import db_backend, db_helpers


def _repo_root(explicit_root: Optional[str] = None) -> Path:
    if explicit_root:
        return Path(explicit_root)
    return Path.cwd()


def _discovery_file(item_num: int) -> Path:
    # Exact legacy scratch-path shape cataloged by the item-ref baseline.
    return Path("/tmp") / f"discovery-scan.YOK-{item_num}.{os.getpid()}"


def _item_context_matcher(public_ref: str) -> Callable[[str], bool]:
    """Return a predicate matching one item's public ref or bare sequence.

    Compiled once per scan rather than once per candidate entry.
    """
    from yoke_contracts.public_ref import parse_public_item_ref

    _, sequence = parse_public_item_ref(public_ref)
    escaped = re.escape(str(sequence))
    public_pattern = re.compile(
        rf"(?i)(^|[^A-Z0-9]){re.escape(public_ref)}(?=$|[^0-9])"
    )
    bare_pattern = re.compile(
        rf"(^|[\s(/_-])0*{escaped}(?=$|[\s/)_-])"
    )

    def matches(context: str) -> bool:
        return bool(
            public_pattern.search(context) or bare_pattern.search(context)
        )

    return matches


def _format_ouroboros_row(row: Any) -> str:
    return "|".join("" if value is None else str(value) for value in tuple(row))


def _read_ouroboros_unreviewed(
    repo_root: Path,
    item_num: int,
) -> tuple[str, int, str]:
    """Return the item's unreviewed entries, their count, and its public ref.

    The ref is rendered from the same connection that reads the entries. An
    unreachable control plane degrades to an empty ref so the caller can fall
    back to the token the operator typed.
    """
    del repo_root  # DB authority comes from the active Postgres binding.
    try:
        conn = db_helpers.connect()
        try:
            from yoke_core.domain.project_identity import render_item_ref

            public_ref = render_item_ref(conn, item_num)
            rows = conn.execute(
                "SELECT o.id, o.timestamp, o.agent, COALESCE(o.context,''), o.category, "
                "replace(o.body, chr(10), ' '), COALESCE(o.reviewed_at,''), "
                "COALESCE(p.slug,'') "
                "FROM ouroboros_entries o "
                "LEFT JOIN projects p ON p.id = o.project_id "
                "WHERE o.reviewed_at IS NULL AND o.archived_at IS NULL "
                "ORDER BY o.id ASC"
            ).fetchall()
        finally:
            conn.close()
    except db_backend.operational_error_types() + (RuntimeError,):
        return "(none)\n", 0, ""
    matches = _item_context_matcher(public_ref)
    scoped_rows = [row for row in rows if matches(str(row[3] or ""))]
    output = "\n".join(_format_ouroboros_row(row) for row in scoped_rows)
    if not output.strip():
        return "(none)\n", 0, public_ref
    count = len([line for line in output.splitlines() if line.strip()])
    return output.rstrip("\n") + "\n", count, public_ref


def run_scan(public_ref: str, *, repo_root: Optional[str] = None, stdout=None, stderr=None) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    root = _repo_root(repo_root)
    from yoke_core.domain.yok_n_parser import parse_item_argument

    try:
        item_num = parse_item_argument(public_ref, cwd=root)
    except ValueError as exc:
        stderr.write(f"Error: {exc}\n")
        return 2

    discovery_file = _discovery_file(item_num)

    ouro_text, ouro_count, item_label = _read_ouroboros_unreviewed(root, item_num)

    scan_output = (
        f"--- Unreviewed ouroboros entries for {item_label or public_ref.strip()} ---\n"
        f"{ouro_text}\n"
        "=== END DISCOVERY SCAN ===\n"
    )
    if ouro_count >= 5:
        scan_output += (
            f"Recommendation: {ouro_count} unreviewed ouroboros entries. "
            "Consider /yoke curate.\n"
        )

    discovery_file.write_text(
        f"DISCOVERY_FILE={discovery_file}\n"
        f"UNREVIEWED_OUROBOROS={ouro_count}\n"
        "---\n"
        f"{scan_output}"
    )

    stdout.write("\n")
    stdout.write("=== Step 9: Discovery scan ===\n")
    stdout.write("Review the output below. File /yoke idea for any untracked discoveries.\n\n")
    stdout.write(scan_output)
    stdout.write(f"DISCOVERY_FILE={discovery_file}\n")
    return 0


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    repo_root = None
    if len(args) >= 2 and args[0] == "--repo-root":
        repo_root = args[1]
        args = args[2:]
    public_ref = args[0] if args else ""
    return run_scan(public_ref, repo_root=repo_root)


if __name__ == "__main__":
    raise SystemExit(main())
