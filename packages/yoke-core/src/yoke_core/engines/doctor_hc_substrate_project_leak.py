"""HC-substrate-project-leak: detect project-named files in the substrate.

The Yoke substrate (``runtime/api/domain/`` and ``runtime/api/engines/``)
holds generic capabilities — validators, doctor HCs, runtime helpers — that
must work for any webapp project. A filename that bakes in a specific
project identifier (for example, ``validate_<project>_pipeline.py``) violates
the generic substrate boundary: the file should read the project at call time.

This HC walks the substrate directories and reports any Python filename
whose lowercase form contains a project identifier from the ``projects``
table other than ``yoke`` (Yoke IS the substrate, so its own name is
allowed). Matches are FAIL findings; an empty substrate scan PASSes. The
HC self-skips when the repo root cannot be resolved or the substrate
directories are absent.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List

from yoke_core.domain.db_helpers import query_rows

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_SLUG = "HC-substrate-project-leak"
_HC_DESC = "Substrate project filename leak"


_SUBSTRATE_DIRS = (
    "runtime/api/domain",
    "runtime/api/engines",
)

# Yoke IS the substrate; its name in a filename is allowed.
_ALLOWED_PROJECT_IDS = frozenset({"yoke"})

# Match project id tokens surrounded by punctuation / underscores while
# ignoring longer words that merely share a prefix.
_TOKEN_BOUNDARY_RE = re.compile(r"[a-zA-Z0-9]+")


def _project_ids_to_scan(conn) -> List[str]:
    if not _base._table_exists(conn, "projects"):
        return []
    rows = query_rows(conn, "SELECT id FROM projects ORDER BY id")
    ids: List[str] = []
    for row in rows:
        pid = (row[0] if not hasattr(row, "keys") else row["id"]) or ""
        pid_str = str(pid).strip().lower()
        if not pid_str or pid_str in _ALLOWED_PROJECT_IDS:
            continue
        ids.append(pid_str)
    return ids


def _iter_substrate_python_files(repo_root: Path) -> Iterable[Path]:
    for rel in _SUBSTRATE_DIRS:
        root = repo_root / rel
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.py")):
            yield path


def _filename_tokens(name: str) -> List[str]:
    return [tok.lower() for tok in _TOKEN_BOUNDARY_RE.findall(name)]


def hc_substrate_project_leak(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    repo_root_str = _base._resolve_repo_root()
    if not repo_root_str:
        rec.record(
            _HC_SLUG, _HC_DESC, "PASS",
            "repo root not resolvable — skipping substrate scan",
        )
        return
    repo_root = Path(repo_root_str)

    project_ids = _project_ids_to_scan(conn)
    if not project_ids:
        rec.record(
            _HC_SLUG, _HC_DESC, "PASS",
            "no non-yoke projects in projects table — nothing to scan against",
        )
        return

    findings: List[str] = []
    for path in _iter_substrate_python_files(repo_root):
        tokens = set(_filename_tokens(path.name))
        for project_id in project_ids:
            if project_id in tokens:
                try:
                    rel = path.resolve().relative_to(repo_root.resolve())
                except ValueError:
                    rel = path
                findings.append(
                    f"- {rel}: substrate filename contains project identifier '{project_id}'"
                )
                break

    if findings:
        rec.record(
            _HC_SLUG, _HC_DESC, "FAIL", "\n".join(findings),
        )
    else:
        rec.record(_HC_SLUG, _HC_DESC, "PASS", "")
