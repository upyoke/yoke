"""Module-file resolution, decision records, and audit-row evidence helpers.

Owns the disk-side primitives the §7.1 scanner and §7.2 evidence gate
consume:

* Module-file resolvers and a tolerant DDL extractor used by the
  opportunistic mechanical scanner.
* Decision-record path resolution + YAML-frontmatter parser used by the
  retire flow.  :func:`decision_record_path` is public surface (re-exported
  from :mod:`yoke_core.domain.db_mutation_gate`).
* Audit-row completion check used by the apply flow on the model's
  authoritative DB.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional, Tuple

from yoke_core.domain import db_backend


# ---------------------------------------------------------------------------
# Module file resolution + DDL extraction
# ---------------------------------------------------------------------------


_GIT_BRANCH_BLOB_RE = re.compile(r"^[0-9a-f]{4,}$", re.IGNORECASE)


def _resolve_module_path(
    repo_path: Path, modules_dir: str, identifier: str
) -> Path:
    return repo_path / modules_dir / f"{identifier}.py"


def _read_module_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


_DDL_DOCSTRING_RE = re.compile(
    r"^\s*(?:#.*\n)*\s*(?:[A-Z]+|migration)?\s*=?\s*(?:[\"']{3})(.*?)(?:[\"']{3})",
    re.DOTALL | re.MULTILINE,
)
_TRIPLE_QUOTED_RE = re.compile(r'(?:"""|\'\'\')(.+?)(?:"""|\'\'\')', re.DOTALL)


def _extract_candidate_ddl(text: str) -> str:
    """Best-effort DDL extraction from a migration module body.

    Migration modules are Python; we don't want to import them.  The
    scanner regexes treat their input as raw SQL.  We return any
    triple-quoted SQL strings we can find; the scanner then checks for
    banned patterns within them.  If nothing matches we return the full
    text — the scanner regexes are safe against non-SQL content.
    """
    matches = _TRIPLE_QUOTED_RE.findall(text)
    if matches:
        return "\n".join(m.strip() for m in matches if m and m.strip())
    return text


# ---------------------------------------------------------------------------
# Decision-record helpers (retire flow)
# ---------------------------------------------------------------------------


_DECISION_RECORD_DIR = Path("docs/archive/decisions")
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def decision_record_path(repo_path: Path, identifier: str) -> Path:
    return repo_path / _DECISION_RECORD_DIR / f"{identifier}.md"


def _parse_yaml_frontmatter(text: str) -> dict:
    """Tiny YAML subset: ``key: value`` per line within the frontmatter block."""
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}
    block = match.group(1)
    out: dict = {}
    for line in block.splitlines():
        if not line.strip() or line.strip().startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if value.lower() == "true":
            out[key] = True
        elif value.lower() == "false":
            out[key] = False
        else:
            out[key] = value
    return out


def _verify_retire_record(
    repo_path: Path,
    identifier: str,
    expected_model: str,
) -> Tuple[bool, str]:
    """Return ``(ok, reason)`` for a single retire decision record."""
    path = decision_record_path(repo_path, identifier)
    if not path.is_file():
        return (
            False,
            f"missing decision record at {_DECISION_RECORD_DIR}/{identifier}.md",
        )
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return False, f"cannot read decision record at {path}: {exc}"
    fm = _parse_yaml_frontmatter(text)
    if not fm:
        return False, f"decision record at {path} has no YAML frontmatter"
    if fm.get("retired-without-apply") is not True:
        return (
            False,
            f"decision record at {path} missing 'retired-without-apply: true' frontmatter",
        )
    if fm.get("migration_module") != identifier:
        return (
            False,
            f"decision record at {path} migration_module field "
            f"({fm.get('migration_module')!r}) does not match identifier '{identifier}'",
        )
    if expected_model and fm.get("model_name") != expected_model:
        return (
            False,
            f"decision record at {path} model_name "
            f"({fm.get('model_name')!r}) does not match profile model_name '{expected_model}'",
        )
    if not str(fm.get("reason") or "").strip():
        return False, f"decision record at {path} has empty 'reason' field"
    if not str(fm.get("retired_at") or "").strip():
        return False, f"decision record at {path} has empty 'retired_at' field"
    return True, ""


# ---------------------------------------------------------------------------
# Audit-row evidence (apply flow)
# ---------------------------------------------------------------------------


def _audit_row_completed_for_module(
    audit_conn: Any,
    project_id: int,
    model_name: str,
    identifier: str,
) -> bool:
    """True if the model's authoritative DB has a completed audit row."""
    p = "%s" if db_backend.connection_is_postgres(audit_conn) else "?"
    cursor = audit_conn.execute(
        "SELECT state FROM migration_audit "
        f"WHERE migration_name = {p} AND project_id = {p} "
        f"AND COALESCE(model_name, {p}) = {p}",
        (identifier, project_id, model_name, model_name),
    )
    for row in cursor.fetchall():
        state_val = row["state"] if hasattr(row, "keys") else row[0]
        if state_val and str(state_val) == "completed":
            return True
    return False


__all__ = [
    "_audit_row_completed_for_module",
    "_extract_candidate_ddl",
    "_parse_yaml_frontmatter",
    "_read_module_text",
    "_resolve_module_path",
    "_verify_retire_record",
    "decision_record_path",
]
