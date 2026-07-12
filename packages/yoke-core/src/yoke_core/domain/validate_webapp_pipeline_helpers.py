"""Shared helpers for the webapp pipeline pre-flight validator.

Exposes the dataclasses, counter print helpers, control-plane DB helpers,
and subprocess helpers consumed by the parent
``validate_webapp_pipeline`` module and its sibling check modules
(``validate_webapp_pipeline_checks_db``,
``validate_webapp_pipeline_checks_remote``).

Classification note: the DB helpers here read Yoke's OWN control plane
(``projects`` / ``project_capabilities`` / ``capability_secrets`` /
``deployment_flows``), whose authority is Postgres. They are not
generic-webapp-validation SQLite — the connection is the active-authority
connection from the backend factory, never a genuine ``sqlite3`` file handle.

The check modules import these symbols via
``from .validate_webapp_pipeline_helpers import _run, _which, ...``
and call them via bareword so tests can monkeypatch the binding visible
to the caller's module namespace.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, List, Optional

from yoke_core.domain.project_github_capability_settings import (
    reject_github_capability_secret_read,
)
from yoke_core.domain.project_identity import ProjectIdentity, resolve_project
from yoke_core.domain.schema_common import (
    _column_exists as _schema_column_exists,
    _table_exists as _schema_table_exists,
)


@dataclass
class ValidateContext:
    """Execution context for the validation run."""

    project_root: Path
    script_dir: Path
    control_plane_marker: Path
    project: str
    verbose: bool = False

    @property
    def project_display(self) -> str:
        return self.project.capitalize()

    @property
    def project_upper(self) -> str:
        return self.project.upper()


@dataclass
class Counters:
    passed: int = 0
    failed: int = 0
    warned: int = 0

    @property
    def total(self) -> int:
        return self.passed + self.failed + self.warned


def _check_pass(counters: Counters, message: str) -> None:
    counters.passed += 1
    print(f"[PASS] {message}")


def _check_fail(counters: Counters, message: str, *hints: str) -> None:
    counters.failed += 1
    print(f"[FAIL] {message}")
    for hint in hints:
        print(f"       {hint}")


def _check_warn(counters: Counters, message: str, *hints: str) -> None:
    counters.warned += 1
    print(f"[WARN] {message}")
    for hint in hints:
        print(f"       {hint}")


# ---------------------------------------------------------------------------
# Control-plane helpers (mirror bootstrap_project.py so the two modules
# stay aligned). These read Yoke's authority, which is Postgres. The
# ``conn`` they pass around is backend-owned, never a genuine
# ``sqlite3.Connection``, so annotations use ``Any``.
# ---------------------------------------------------------------------------


def _connect(control_plane_marker: Path) -> Any:
    # Route through the backend factory: Yoke authority is Postgres, so the
    # DSN-pointed control plane is read here and ``control_plane_marker`` is an
    # ignored compatibility slot (the github-auth resolver this module pairs
    # with connects via the same factory, keeping both reads on one database).
    # Table/column existence checks delegate to schema_common, which reads
    # native Postgres catalogs.
    from yoke_core.domain import db_backend

    return db_backend.connect(str(control_plane_marker))


def _query_scalar(
    conn: Any, sql: str, params: tuple = ()
) -> Optional[str]:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    value = row[0]
    return None if value is None else str(value)


def _p(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _table_exists(conn: Any, table: str) -> bool:
    return _schema_table_exists(conn, table)


def _column_exists(conn: Any, table: str, column: str) -> bool:
    return _schema_column_exists(conn, table, column)


def _load_json(value: Optional[str]) -> dict:
    if not value:
        return {}
    try:
        data = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _resolve_project_identity(conn: Any, project: str) -> ProjectIdentity:
    ident = resolve_project(conn, project)
    assert ident is not None
    return ident


def _capability_settings(
    conn: Any, project: str, cap_type: str
) -> dict:
    if not _table_exists(conn, "project_capabilities"):
        return {}
    ident = _resolve_project_identity(conn, project)
    if _column_exists(conn, "project_capabilities", "settings"):
        settings = _query_scalar(
            conn,
            "SELECT COALESCE(settings, '{}') FROM project_capabilities "
            f"WHERE project_id={_p(conn)} AND type={_p(conn)}",
            (ident.id, cap_type),
        )
        parsed = _load_json(settings)
        if parsed:
            return parsed
    config = _query_scalar(
        conn,
        "SELECT COALESCE(settings, '{}') FROM project_capabilities "
        f"WHERE project_id={_p(conn)} AND type={_p(conn)}",
        (ident.id, cap_type),
    )
    return _load_json(config)


def _capability_secret(
    conn: Any, project: str, cap_type: str, key: str
) -> str:
    reject_github_capability_secret_read(cap_type)
    ident = _resolve_project_identity(conn, project)
    if _table_exists(conn, "capability_secrets"):
        row = _query_scalar(
            conn,
            "SELECT value FROM capability_secrets "
            f"WHERE project_id={_p(conn)} AND type={_p(conn)} AND key={_p(conn)}",
            (ident.id, cap_type, key),
        )
        if row:
            return row
    return str(_capability_settings(conn, project, cap_type).get(key, "") or "")


# ---------------------------------------------------------------------------
# Subprocess helpers (kept patchable in tests)
# ---------------------------------------------------------------------------


def _run(
    cmd: List[str],
    *,
    cwd: Optional[Path] = None,
    stdin: Optional[str] = None,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        input=stdin,
        text=True,
        capture_output=True,
        cwd=str(cwd) if cwd else None,
    )


def _which(cmd: str) -> bool:
    return shutil.which(cmd) is not None
