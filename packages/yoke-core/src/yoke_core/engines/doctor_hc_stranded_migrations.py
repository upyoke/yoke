"""HC-stranded-migration-module: detect retired-but-not-deleted modules.

Defense-in-depth backstop for the cutover-ticket AC wording. The
governed migration runner now auto-retires module files for
single-install models after live-apply (see
:mod:`yoke_core.domain.migration_auto_retire`), and refine's review
rubric verifies the ticket's retire-AC matches the project's install
topology. This HC catches the residual case: a migration whose
``migration_audit.state='completed'`` row exists on its migration target
while the module file still sits under the model's declared
``modules_dir``.

The HC iterates every project that declares a ``migration_model``
capability — Yoke and Buzz today, future governed projects
automatically. For each project it resolves ``modules_dir`` and
``authoritative_db.kind`` from the capability payload, joins against the
project's migration ``migration_audit`` table, and reports stranded
modules keyed by project. ``postgres`` projects read the connected
control-plane connection the Doctor already holds; ``sqlite_file``
projects open their declared external/archive file. Yoke itself must be
Postgres-backed here; ``project='yoke'`` with ``sqlite_file`` and root
``data/yoke.db`` paths are ignored as invalid legacy residue. There is no
Yoke-only fallback scan: without governed project metadata, the HC passes
closed rather than reconstructing authority from repo paths.

Surface: WARN with the affected module names and a one-line
remediation pointer. The HC does not auto-delete — operator confirms
the deletion via the normal ``/yoke idea`` flow when the audit looks
suspicious, or via direct ``git rm`` when the audit is clean.

Skipped: modules whose ``migration_audit`` rows show only failed states
(no completed row) — those are still in flight or rolled back.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_checkout_locations import checkout_for_project
from yoke_core.domain.sqlite_validation_boundary import (
    is_retired_root_yoke_db_path,
)

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


_HC_NAME = "HC-stranded-migration-module"
_HC_DESC = "Completed migration module(s) still present in the live tree"


@dataclass(frozen=True)
class _GovernedProject:
    project: str
    model_name: str
    authoritative_kind: str
    modules_dir_rel: str
    modules_dir_abs: Path
    audit_db_abs: Optional[Path] = None


def _list_module_files(modules_dir: Path) -> List[str]:
    if not modules_dir.is_dir():
        return []
    out: List[str] = []
    for p in sorted(modules_dir.glob("*.py")):
        if p.name.startswith("_"):
            continue
        out.append(p.stem)
    return out


def _governed_projects(conn) -> List[_GovernedProject]:
    """Discover every project declaring a migration_model capability.

    Returns ``[]`` when ``project_capabilities`` is absent or the join
    fails. The caller treats that as clean: active authority must come from
    governed project metadata, not a reconstructed Yoke SQLite path.
    """
    if not (
        _base._table_exists(conn, "project_capabilities")
        and _base._table_exists(conn, "projects")
    ):
        return []
    try:
        rows = query_rows(
            conn,
            "SELECT p.slug AS project, pc.settings AS settings "
            "FROM project_capabilities pc "
            "JOIN projects p ON p.id = pc.project_id "
            "WHERE pc.type = 'migration_model'",
        )
    except db_backend.operational_error_types(conn=conn):
        return []

    out: List[_GovernedProject] = []
    for row in rows:
        project = row["project"]
        checkout = checkout_for_project(conn, str(project))
        repo_path = str(checkout) if checkout is not None else ""
        if not project or not repo_path:
            continue
        try:
            payload = json.loads(row["settings"] or "{}")
        except json.JSONDecodeError:
            continue
        default_model = payload.get("default_model")
        models = payload.get("models") or {}
        model_payload = models.get(default_model) if default_model else None
        if not isinstance(model_payload, dict):
            continue
        modules_dir_rel = (
            ((model_payload.get("runner") or {}).get("config") or {})
            .get("modules_dir")
        )
        auth = model_payload.get("authoritative_db") or {}
        authoritative_kind = auth.get("kind")
        if not isinstance(modules_dir_rel, str) or not modules_dir_rel:
            continue
        modules_dir_abs = (Path(repo_path) / modules_dir_rel).resolve()
        audit_db_abs: Optional[Path] = None
        if authoritative_kind == "sqlite_file":
            if str(project) == "yoke":
                continue
            audit_db_rel = (auth.get("location") or {}).get("path")
            if not isinstance(audit_db_rel, str) or not audit_db_rel:
                continue
            audit_db_abs = (Path(repo_path) / audit_db_rel).resolve()
            if is_retired_root_yoke_db_path(audit_db_abs):
                continue
        elif authoritative_kind != "postgres":
            continue
        out.append(_GovernedProject(
            project=str(project),
            model_name=str(default_model),
            authoritative_kind=str(authoritative_kind),
            modules_dir_rel=modules_dir_rel,
            modules_dir_abs=modules_dir_abs,
            audit_db_abs=audit_db_abs,
        ))
    return out


def _completed_modules_from_conn(conn, present: List[str]) -> List[str]:
    """Return present module identifiers with completed audit rows on conn."""
    try:
        if not _base._table_exists(conn, "migration_audit"):
            return []
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        placeholders = ",".join(marker for _ in present)
        rows = query_rows(
            conn,
            f"SELECT migration_name FROM migration_audit "
            f"WHERE state='completed' "
            f"  AND migration_name IN ({placeholders})",
            tuple(present),
        )
    except db_backend.operational_error_types(conn=conn):
        return []
    return sorted({str(r["migration_name"]) for r in rows})


def _completed_modules_on_sqlite_file(
    audit_db: Optional[Path], present: List[str],
) -> List[str]:
    """Read ``migration_audit`` from a declared external/archive SQLite file."""
    if audit_db is None or not audit_db.is_file():
        return []
    try:
        audit_conn = sqlite3.connect(str(audit_db))
        audit_conn.row_factory = sqlite3.Row
    except sqlite3.Error:
        return []
    try:
        return _completed_modules_from_conn(audit_conn, present)
    finally:
        audit_conn.close()


def _scan_governed_projects(conn) -> List[str]:
    """Project-aware path. Returns assembled WARN-detail lines."""
    governed = _governed_projects(conn)
    if not governed:
        return []
    issues: List[str] = []
    for gp in governed:
        present = _list_module_files(gp.modules_dir_abs)
        if not present:
            continue
        if gp.authoritative_kind == "postgres":
            completed = _completed_modules_from_conn(conn, present)
        else:
            completed = _completed_modules_on_sqlite_file(gp.audit_db_abs, present)
        if not completed:
            continue
        issues.append(
            f"- {gp.project}: {len(completed)} module(s) have "
            f"`migration_audit.state='completed'` but the module file "
            f"is still present under `{gp.modules_dir_rel}/`. "
            f"Per `AGENTS.md` `## Cutover-ticket AC wording`, "
            f"single-install completed modules retire in the same "
            f"slice as live-apply; multi-install modules retire after "
            f"every install records completion."
        )
        for name in completed:
            issues.append(f"  - {name}")
        issues.append(
            f"  Remediation: confirm the audit reflects target "
            f"completion, then "
            f"`git rm {gp.modules_dir_rel}/<name>.py` and any "
            f"declared `test_<name>.py` companion under the project's "
            f"`project_structure.test_roots`."
        )
    return issues


def hc_stranded_migration_module(
    conn, args: DoctorArgs, rec: RecordCollector,
) -> None:
    issues = _scan_governed_projects(conn)
    if not issues:
        rec.record(_HC_NAME, _HC_DESC, "PASS", "")
        return
    rec.record(_HC_NAME, _HC_DESC, "WARN", "\n".join(issues))


__all__ = ["hc_stranded_migration_module"]
