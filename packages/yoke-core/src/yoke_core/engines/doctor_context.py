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

from yoke_contracts.install_binding import (
    is_yoke_source_checkout,
    source_checkout_root,
)
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
    through the server-mode environment; a runner that either maps checkouts
    or is itself executing from a source tree is a developer machine; a
    runner with neither is a control-plane runtime, which is what a wheel
    install in a container looks like.
    """
    selected = str(declared or "").strip()
    if selected in RUNTIMES:
        return selected
    if os.environ.get(SERVER_MODE_ENV, "").strip() == SERVER_MODE_SELF_HOST:
        return RUNTIME_SERVER
    if _mapped_checkouts() or running_source_root():
        return RUNTIME_LOCAL
    return RUNTIME_HOSTED


def resolve_self_project(conn) -> Optional[str]:
    """The project that owns this Yoke installation, by checkout evidence.

    The self project is whichever mapped project's checkout *is* the Yoke
    source tree. Reading it from the checkout binding rather than a literal
    slug keeps a renamed self project resolvable, and returns ``None`` on a
    runner that holds no checkout at all.
    """
    names = self_project_names(conn)
    return next(iter(sorted(names)), None) if names else None


def self_project_names(conn) -> frozenset:
    """Every identifier that names the project owning this installation.

    The checkout binding is the evidence, and it yields a project id without
    touching the database. The slug is the friendlier name but needs a
    readable ``projects`` table; when that read cannot answer — a fresh or
    minimal database — the seeded slug stands in, because the checkout is
    demonstrably the Yoke source tree even if this database cannot name it.
    Returning the whole set lets a run match on whichever identifier the
    caller happened to use.

    The checkout map is env-scoped, so it can come back empty on a machine
    that holds the source anyway. The running import is the fallback
    evidence: code loaded from inside a checkout's ``packages/`` tree *is*
    the Yoke source, whatever the config says. A wheel install resolves from
    site-packages and yields nothing, which is the honest answer for a
    control-plane server.
    """
    for checkout, project_id in _mapped_checkouts():
        try:
            root = Path(checkout).expanduser()
        except (TypeError, ValueError):
            continue
        if not is_yoke_source_checkout(root):
            continue
        names = {str(project_id)}
        slug = _project_slug(conn, project_id)
        names.add(slug if slug else DEFAULT_PROJECT_SLUG)
        return frozenset(names)
    return frozenset({DEFAULT_PROJECT_SLUG}) if running_source_root() else frozenset()


def running_source_root() -> Optional[Path]:
    """The Yoke source checkout this engine is running from, if any."""
    return source_checkout_root(__file__)


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
    names = self_project_names(conn)
    if resolved_runtime in CHECKOUT_BEARING_RUNTIMES:
        try:
            checkout = checkout_for_project(conn, project)
        except Exception:  # noqa: BLE001 - context reads are advisory
            checkout = None
        if checkout is None and project in {str(name) for name in names}:
            # The checkout map did not answer, but the engine is running
            # from the source tree the self project owns — that tree is the
            # checkout this run can read.
            checkout = running_source_root()
        if checkout is not None and not Path(checkout).is_dir():
            checkout = None
    return DoctorContext(
        project=project,
        runtime=resolved_runtime,
        self_project=next(iter(sorted(names))) if names else None,
        self_project_names=names,
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
    "running_source_root",
    "self_project_names",
]
