"""Shared helpers for the ``bootstrap_project`` family.

Hosts the ``BootstrapContext``/``SetupConfig`` dataclasses and every
small utility — DB connection routing, capability lookups, the ``_run``
subprocess wrapper, and the formatted print helpers — used by the
preflight, setup, and verify entry points.
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from yoke_core.domain import db_backend, db_helpers
from yoke_core.domain.project_checkout_locations import checkout_for_project
from yoke_core.domain.project_github_capability_settings import (
    reject_github_capability_secret_read,
)
from yoke_core.domain.project_identity import ProjectIdentity, resolve_project
from yoke_core.domain.schema_common import (
    _column_exists as _schema_column_exists,
    _table_exists as _schema_table_exists,
)


@dataclass(frozen=True)
class BootstrapContext:
    project: str
    project_root: Path
    script_dir: Path
    yoke_db: Path
    packs: tuple[str, ...] = ()

    @property
    def project_upper(self) -> str:
        return self.project.upper()


@dataclass(frozen=True)
class SetupConfig:
    project: str
    display_name: str
    repo_path: Path
    ssh_host: str
    ssh_user: str
    ssh_key_path: Path


def _connect(_db_path: Path | None = None) -> Any:
    """Connect to the active Yoke authority.

    ``BootstrapContext.yoke_db`` is a retired launcher token, not database
    authority. Bootstrap helpers always route through the configured backend.
    """
    return db_helpers.connect()


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _query_scalar(conn: Any, sql: str, params: tuple = ()) -> Optional[str]:
    row = conn.execute(sql, params).fetchone()
    if row is None:
        return None
    value = row[0]
    return None if value is None else str(value)


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


def _capability_settings(conn: Any, project: str, cap_type: str) -> dict:
    if not _table_exists(conn, "project_capabilities"):
        return {}
    if not _column_exists(conn, "project_capabilities", "settings"):
        return {}
    ident = _resolve_project_identity(conn, project)
    p = _p(conn)
    settings = _query_scalar(
        conn,
        "SELECT COALESCE(settings, '{}') FROM project_capabilities "
        f"WHERE project_id={p} AND type={p}",
        (ident.id, cap_type),
    )
    return _load_json(settings)


def _capability_secret(conn: Any, project: str, cap_type: str, key: str) -> str:
    reject_github_capability_secret_read(cap_type)
    ident = _resolve_project_identity(conn, project)
    if _table_exists(conn, "capability_secrets"):
        p = _p(conn)
        row = _query_scalar(
            conn,
            f"SELECT value FROM capability_secrets WHERE project_id={p} AND type={p} AND key={p}",
            (ident.id, cap_type, key),
        )
        if row:
            return row
    return str(_capability_settings(conn, project, cap_type).get(key, "") or "")


def _run(
    cmd: list[str],
    *,
    stdin: Optional[str] = None,
    cwd: Optional[Path] = None,
    env: Optional[dict[str, str]] = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        input=stdin,
        text=True,
        capture_output=True,
        cwd=str(cwd) if cwd else None,
        env=env,
    )


def _print_pass(message: str) -> None:
    print(f"[PASS] {message}")


def _print_fail(message: str, *actions: str) -> None:
    print(f"[FAIL] {message}")
    print()
    print("  ACTION REQUIRED:")
    for action in actions:
        print(f"  {action}")
    print()


def _warn(message: str) -> None:
    print(f"[WARN] {message}")


class SshKeyResolutionError(ValueError):
    """Raised when no SSH key path can be resolved from env or DB."""


def _resolve_ssh_key_path(project_upper: str, ssh_settings: dict) -> Path:
    """Resolve env-var > DB > error. Tilde-expand. No silent fallback."""
    env_key_name = f"{project_upper}_SSH_KEY_PATH"
    env_val = os.environ.get(env_key_name, "").strip()
    db_val = str(ssh_settings.get("key_path", "") or "").strip()
    chosen = env_val or db_val
    if not chosen:
        raise SshKeyResolutionError(
            f"No SSH key path configured for project '{project_upper.lower()}'. "
            f"Set the env var {env_key_name} or store key_path in "
            "project_capabilities.ssh.settings (preserves existing host/user)."
        )
    return Path(chosen).expanduser()


def _validate_ssh_key_parseable(key_path: Path) -> tuple[bool, str]:
    """Run ``ssh-keygen -y -f`` to confirm the key parses. Returns ``(ok, msg)``."""
    result = _run(["ssh-keygen", "-y", "-f", str(key_path)])
    if result.returncode == 0:
        return True, (result.stdout or "").strip()
    err = (result.stderr or result.stdout or "").strip()
    return False, err or f"ssh-keygen -y -f {key_path} exited {result.returncode}"


def _persist_resolved_ssh_key_path(ctx: BootstrapContext, key_path: Path) -> None:
    """Merge ``key_path`` into ssh capability settings, preserving host/user.

    Routes through the value-CAS merge surface so a concurrent settings
    writer composes instead of being erased (and absent ssh capabilities
    are created from the empty object).
    """
    from yoke_core.domain.projects_capabilities_settings import (
        cmd_capability_merge_settings,
    )

    cmd_capability_merge_settings(ctx.project, "ssh", {"key_path": str(key_path)})


def _probe_ssh_auth(ssh_user: str, ssh_host: str, key_path: Path) -> tuple[bool, str]:
    """``ssh -i <key> -o BatchMode=yes <user>@<host> true``. Returns ``(ok, msg)``."""
    result = _run(
        [
            "ssh",
            "-i",
            str(key_path),
            "-o",
            "BatchMode=yes",
            "-o",
            "StrictHostKeyChecking=accept-new",
            "-o",
            "ConnectTimeout=5",
            f"{ssh_user}@{ssh_host}",
            "true",
        ]
    )
    if result.returncode == 0:
        return True, ""
    err = (result.stderr or result.stdout or "").strip()
    return (
        False,
        err or f"ssh probe to {ssh_user}@{ssh_host} exited {result.returncode}",
    )


def _load_setup_config(ctx: BootstrapContext) -> SetupConfig:
    conn = _connect()
    try:
        ident = _resolve_project_identity(conn, ctx.project)
        p = _p(conn)
        checkout = checkout_for_project(conn, ident.slug)
        if checkout is None:
            # A repo-tree writer with no resolved checkout must fail loudly.
            # Falling through to an empty repo_path lands cfg.repo_path on
            # Path() (the current working directory), and setup would then
            # render workflow files into whatever unrelated checkout the
            # process happens to run from (see the cwd-pollution regression).
            raise FileNotFoundError(
                f"project {ident.slug!r} has no machine-local checkout mapping; "
                "refusing to fall back to the current directory to write "
                "rendered files into an unrelated checkout"
            )
        repo_path = str(checkout)
        display_name = (
            _query_scalar(conn, f"SELECT name FROM projects WHERE id={p}", (ident.id,))
            or ident.slug
        )
        ssh_settings = _capability_settings(conn, ctx.project, "ssh")
    finally:
        conn.close()

    ssh_key_path = _resolve_ssh_key_path(ident.slug.upper(), ssh_settings)

    return SetupConfig(
        project=ident.slug,
        display_name=display_name,
        repo_path=Path(repo_path).expanduser(),
        ssh_host=str(ssh_settings.get("host", "") or ""),
        ssh_user=str(ssh_settings.get("user", "") or ""),
        ssh_key_path=ssh_key_path,
    )


def _expected_workflow_names(
    ctx: BootstrapContext,
    display_name: str,
    workflows_dir: Path | None = None,
) -> list[str]:
    if workflows_dir is not None and workflows_dir.is_dir():
        names: list[str] = []
        for wf in sorted(workflows_dir.glob("*.yml")):
            for line in wf.read_text().splitlines():
                if line.startswith("name:"):
                    names.append(line.split(":", 1)[1].strip())
                    break
        if names:
            return names
    return [
        f"{display_name} Deploy",
        f"{display_name} Smoke Test",
        f"{display_name} Ephemeral Environment",
        f"{display_name} Ephemeral Teardown",
    ]


def _decode_base64(text: str) -> str:
    raw = text.strip()
    if not raw:
        return ""
    try:
        return base64.b64decode(raw).decode()
    except Exception:
        return ""
