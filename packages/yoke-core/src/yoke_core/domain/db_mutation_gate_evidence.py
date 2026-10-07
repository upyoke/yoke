"""Module-file resolution, decision records, and audit-row evidence helpers.

Owns the disk-side primitives the opportunistic scanner and the gates
consume:

* Module-file resolvers and a tolerant DDL extractor used by the
  opportunistic mechanical scanner.
* Decision-record path resolution + YAML-frontmatter parser used by the
  retire flow.  :func:`decision_record_path` is public surface (re-exported
  from :mod:`yoke_core.domain.db_mutation_gate`).
Rehearsal receipts are read by :mod:`yoke_core.domain.migration_rehearsal_evidence`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional



# ---------------------------------------------------------------------------
# Module file resolution + DDL extraction
# ---------------------------------------------------------------------------


_GIT_BRANCH_BLOB_RE = re.compile(r"^[0-9a-f]{4,}$", re.IGNORECASE)


def _resolve_module_path(
    repo_path: Path, modules_dir: str, identifier: str
) -> Path:
    """Locate a declared module the way the applier discovers it.

    History entries are ``NNNN_slug.py``, so an item that names the slug does
    not name the filename. Resolving by slug as well as by full stem keeps a
    declaration valid across a renumbering — a squash renumbers entries, it
    does not rename them — and stops the scanner silently reading nothing when
    the two differ.
    """
    directory = repo_path / modules_dir
    exact = directory / f"{identifier}.py"
    if exact.is_file():
        return exact
    suffix = f"_{identifier}.py"
    match = next(
        (p for p in sorted(directory.glob("*.py")) if p.name.endswith(suffix)),
        None,
    )
    return match if match is not None else exact


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


__all__ = [
    "_extract_candidate_ddl",
    "_parse_yaml_frontmatter",
    "_read_module_text",
    "_resolve_module_path",
    "decision_record_path",
]
