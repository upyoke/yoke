"""Resolve the live facts a doctor run derives its applicable set from.

Every fact here is read from evidence the runner actually holds — the
machine-local checkout map, the declared server mode, the target project's
capability rows — never from a hard-coded project slug and never from an
ambient repo-root walk. That keeps the resolution honest on a control-plane
server, which has no checkout and must not resolve one. The two
directory-relative helpers take their directory from the caller for the same
reason: only a client entrypoint knows where the operator is standing.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from yoke_contracts.install_binding import is_yoke_source_checkout
from yoke_contracts.machine_config.schema import mapped_checkouts
from yoke_contracts.project_defaults import (
    DEFAULT_PROJECT_SLUG,
    default_project_for_directory,
)
from yoke_contracts.server_mode import SERVER_MODE_ENV, SERVER_MODE_SELF_HOST

from yoke_core.domain import db_backend, machine_config
from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_checkout_locations import checkout_for_project
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.engines.doctor_applicability import (
    CHECKOUT_BEARING_RUNTIMES,
    DoctorContext,
    RUNTIMES,
    RUNTIME_HOSTED,
    RUNTIME_LOCAL,
    RUNTIME_SERVER,
)

#: Project a run falls back to when nothing names one and the runner is
#: standing nowhere the machine config recognises.
FALLBACK_PROJECT = DEFAULT_PROJECT_SLUG


def resolve_runtime(declared: Optional[str] = None) -> str:
    """Which deployment destination is executing this run.

    An explicit *declared* value wins so a client can state its own runtime
    and tests can pin one. Otherwise: a self-hosted server announces itself
    through the server-mode environment; a runner with no machine-local
    checkout map at all is a control-plane runtime rather than a developer
    machine; everything else is the local universe.
    """
    selected = str(declared or "").strip()
    if selected in RUNTIMES:
        return selected
    if os.environ.get(SERVER_MODE_ENV, "").strip() == SERVER_MODE_SELF_HOST:
        return RUNTIME_SERVER
    return RUNTIME_LOCAL if _mapped_checkouts() else RUNTIME_HOSTED


def resolve_self_project(conn) -> Optional[str]:
    """The project that owns this Yoke installation, by checkout evidence.

    The self project is whichever mapped project's checkout *is* the Yoke
    source tree. Reading it from the checkout binding rather than a literal
    slug keeps a renamed self project resolvable, and returns ``None`` on a
    runner that holds no checkout at all.
    """
    for checkout, project_id in _mapped_checkouts():
        try:
            root = Path(checkout).expanduser()
        except (TypeError, ValueError):
            continue
        if is_yoke_source_checkout(root):
            return _project_slug(conn, project_id)
    return None


def project_capabilities(conn, project: str) -> frozenset:
    """Capability types *project* declares, or an empty set.

    Best-effort: context resolution must never be the reason a doctor run
    fails. An unreadable capability table yields no capabilities, which
    reports capability-gated checks as not-applicable — visible in the
    report rather than silent.
    """
    from yoke_core.engines.doctor_report import _table_exists

    try:
        if not _table_exists(conn, "project_capabilities"):
            return frozenset()
        project_id = resolve_project_id(conn, project)
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        rows = query_rows(
            conn,
            f"SELECT type FROM project_capabilities WHERE project_id = {marker}",
            (project_id,),
        )
    except Exception:  # noqa: BLE001 - context reads are advisory
        return frozenset()
    return frozenset(str(row[0]) for row in rows if row[0])


def resolve_context(conn, args, *, runtime: Optional[str] = None) -> DoctorContext:
    """Assemble the :class:`DoctorContext` for one doctor run."""
    resolved_runtime = resolve_runtime(runtime or getattr(args, "runtime", None))
    project = str(args.project)
    checkout = None
    if resolved_runtime in CHECKOUT_BEARING_RUNTIMES:
        try:
            checkout = checkout_for_project(conn, project)
        except Exception:  # noqa: BLE001 - context reads are advisory
            checkout = None
        if checkout is not None and not Path(checkout).is_dir():
            checkout = None
    return DoctorContext(
        project=project,
        runtime=resolved_runtime,
        self_project=resolve_self_project(conn),
        source_checkout=checkout,
        capabilities=project_capabilities(conn, project),
    )


def default_project(directory: Path) -> str:
    """The project a doctor run targets when the caller named none."""
    return default_project_for_directory(directory)


def _mapped_checkouts() -> list:
    try:
        return list(mapped_checkouts(machine_config.load_config()))
    except Exception:  # pragma: no cover - an unreadable config is not fatal
        return []


def _project_slug(conn, project_id) -> Optional[str]:
    try:
        marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
        rows = query_rows(
            conn,
            f"SELECT slug FROM projects WHERE id = {marker}",
            (int(project_id),),
        )
    except Exception:  # noqa: BLE001 - context reads are advisory
        return None
    return str(rows[0][0]) if rows else None


__all__ = [
    "FALLBACK_PROJECT",
    "default_project",
    "project_capabilities",
    "resolve_context",
    "resolve_runtime",
    "resolve_self_project",
]
