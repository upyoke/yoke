"""Discovery scan helper for done-transition gates."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Optional

from yoke_core.domain import db_backend, db_helpers


_ITEM_RE = re.compile(r"^(?:[Yy][Oo][Kk]-)?([0-9]+)$")


def _normalize_item(raw: str) -> str:
    match = _ITEM_RE.fullmatch(raw)
    if not match:
        return ""
    value = match.group(1).lstrip("0")
    return value or "0"


def _repo_root(explicit_root: Optional[str] = None) -> Path:
    if explicit_root:
        return Path(explicit_root)
    return Path.cwd()


def _discovery_file(item_num: str) -> Path:
    return Path("/tmp") / f"discovery-scan.YOK-{item_num}.{os.getpid()}"


def _context_matches_item(context: str, item_num: str) -> bool:
    normalized = item_num.lstrip("0") or "0"
    escaped = re.escape(normalized)
    sun_pattern = re.compile(
        rf"(?i)(^|[^A-Z0-9])YOK-0*{escaped}(?=$|[^0-9])"
    )
    bare_pattern = re.compile(
        rf"(^|[\s(/_-])0*{escaped}(?=$|[\s/)_-])"
    )
    return bool(sun_pattern.search(context) or bare_pattern.search(context))


def _format_ouroboros_row(row: Any) -> str:
    return "|".join("" if value is None else str(value) for value in tuple(row))


def _read_ouroboros_unreviewed(repo_root: Path, item_num: str) -> tuple[str, int]:
    del repo_root  # DB authority comes from the active Postgres binding.
    try:
        conn = db_helpers.connect()
        try:
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
        return "(none)\n", 0
    scoped_rows = [
        row for row in rows
        if _context_matches_item(str(row[3] or ""), item_num)
    ]
    output = "\n".join(_format_ouroboros_row(row) for row in scoped_rows)
    if not output.strip():
        return "(none)\n", 0
    count = len([line for line in output.splitlines() if line.strip()])
    return output.rstrip("\n") + "\n", count


def run_scan(item_ref: str, *, repo_root: Optional[str] = None, stdout=None, stderr=None) -> int:
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    item_num = _normalize_item(item_ref)
    if not item_num:
        stderr.write(
            "Usage: python3 -m yoke_core.domain.discovery_scan <item-number>\n"
        )
        return 2

    root = _repo_root(repo_root)
    discovery_file = _discovery_file(item_num)

    ouro_text, ouro_count = _read_ouroboros_unreviewed(root, item_num)

    scan_output = (
        f"--- Unreviewed ouroboros entries for YOK-{item_num} ---\n"
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
    item_ref = args[0] if args else ""
    return run_scan(item_ref, repo_root=repo_root)


if __name__ == "__main__":
    raise SystemExit(main())
