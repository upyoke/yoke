"""Export the active universe's database to one portable dump artifact.

One schema runs in every deployment mode, so moving a universe between
modes (local / self-host / hosted) is dump-and-restore; this module owns
the dump half. :func:`export_universe` runs ``pg_dump`` in custom format
(``--format=custom``): a single self-contained, compressed archive that
``pg_restore`` can list, filter, and restore through the portability
validator, where plain SQL text would lose selective-restore and
parallel-restore ability.

Authority is DSN possession. Export is sanctioned when the active
machine-config connection is a non-prod Postgres connection whose DSN
this machine holds (the local universe's shape). An https connection
holds no DSN — a hosted org admin downloads through the dashboard's
``Move universe`` action; a self-host operator backs up at the server
authority — and prod-flagged Postgres connections stay operator-only like
every other direct prod authority. ``pg_dump`` resolves from the embedded engine's installed
binaries first, then ``PATH`` — the same rule the cluster lifecycle
uses for ``initdb``/``pg_ctl``.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

from yoke_core.domain import postgres_binaries
from yoke_core.domain import runtime_settings
from yoke_core.domain import universe_portability

#: pg_dump custom-format archive (``pg_restore``-compatible, compressed).
ARTIFACT_FORMAT = "pg_dump-custom"

ARTIFACT_SUFFIX = ".dump"

#: Machine-settings key capping the dump subprocess runtime.
EXPORT_TIMEOUT_SETTING = "universe_export_timeout_seconds"
DEFAULT_EXPORT_TIMEOUT_S = 600

_FILENAME_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


class UniverseExportError(RuntimeError):
    """The universe could not be exported (authority, connection, or dump)."""


def default_artifact_name(
    org_slug: str, now: Optional[datetime] = None,
) -> str:
    """``<org-slug>-universe-<utc-timestamp>.dump``."""
    stamp = (now or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    cleaned = _FILENAME_SAFE_RE.sub("-", org_slug).strip("-.")
    return f"{cleaned or 'universe'}-universe-{stamp}{ARTIFACT_SUFFIX}"


def resolve_export_dsn() -> str:
    """The active connection's DSN when export is sanctioned, else raise.

    Sanction rule: a non-prod Postgres connection whose credentials this
    machine holds. https refuses (the client holds no DSN; server-side
    export for hosted/self-host universes is a platform surface that has
    not shipped). Prod-flagged Postgres refuses (operator-only).
    """
    from yoke_contracts.machine_config.schema import connection_is_prod
    from yoke_core.domain import db_backend, yoke_connected_env

    try:
        env = yoke_connected_env.load_active()
    except yoke_connected_env.ConnectedEnvError as exc:
        raise UniverseExportError(
            f"the machine's active connection could not be read: {exc}"
        ) from exc
    if env is None:
        raise UniverseExportError(
            "no active connection is configured on this machine; "
            "`yoke init --local` creates a local universe to export"
        )
    if env.backend != "postgres":
        raise UniverseExportError(
            f"the active connection {env.environment!r} is "
            f"{env.backend}-transport (hosted/self-host mode): this machine "
            "does not hold the universe database's DSN, and export requires "
            "DSN possession. A hosted org admin downloads from the "
            "dashboard's `Move universe` action; a self-host operator owns "
            "the server-side backup authority. To export a machine-local "
            "universe, switch to its "
            "env (`yoke env use local`) or create one (`yoke init --local`)."
        )
    if connection_is_prod(env.config):
        raise UniverseExportError(
            f"the active connection {env.environment!r} is a prod-flagged "
            "Postgres connection: direct prod database authority is "
            "operator-only, so `yoke universe export` refuses it. Drive "
            "prod data through the sanctioned operator/admin surfaces."
        )
    try:
        resolved = yoke_connected_env.resolve_postgres_dsn(
            dsn_env=db_backend.PG_DSN_ENV,
            dsn_file_env=db_backend.PG_DSN_FILE_ENV,
        )
    except yoke_connected_env.ConnectedEnvError as exc:
        raise UniverseExportError(
            f"the active connection's DSN could not be resolved: {exc}"
        ) from exc
    return resolved.dsn


def export_universe(
    *,
    out: Optional[Union[str, Path]] = None,
    dsn: Optional[str] = None,
    emit: Callable[[str], None] = lambda _line: None,
) -> Dict[str, Any]:
    """Dump the active universe's database to one custom-format artifact.

    ``dsn=None`` resolves (and sanction-checks) the active connection; an
    explicit ``dsn`` is the injection seam for tests and operator tooling.
    ``out`` routing: ``None`` writes to the current working directory; a
    trailing path separator always means a directory (created when
    missing — pass the raw string, ``Path`` drops the separator); an
    existing directory stays a directory; any other path is the target
    file. Directory targets get the default filename, which embeds the
    org slug and a UTC timestamp. Returns a payload naming the artifact
    path, size, org slug, and archive format.
    """
    resolved_dsn = dsn if dsn is not None else resolve_export_dsn()
    org_slug = _org_slug(resolved_dsn)
    dest = _resolve_destination(out, org_slug)
    emit(f"  [universe-export] dumping org {org_slug!r} universe -> {dest}")
    timeout = runtime_settings.get_seconds(
        EXPORT_TIMEOUT_SETTING, DEFAULT_EXPORT_TIMEOUT_S,
    )
    try:
        inspection = universe_portability.dump_universe(
            resolved_dsn,
            dest,
            timeout_s=timeout,
        )
    except universe_portability.UniversePortabilityError as exc:
        if isinstance(exc.__cause__, FileNotFoundError):
            raise UniverseExportError(
                "pg_dump is missing: expected the embedded engine binaries at "
                f"{postgres_binaries.version_dir() / 'bin'} and found no "
                "pg_dump on PATH. Run `yoke local-postgres start` "
                "(or `yoke init --local`) to refetch the embedded engine."
            ) from exc
        dest.unlink(missing_ok=True)
        raise UniverseExportError(
            "pg_dump failed without leaving an artifact; see the redacted "
            "universe-export diagnostic in the local log. If the embedded "
            "Postgres is stopped, `yoke local-postgres start` brings it up."
        ) from exc
    size_bytes = inspection.size_bytes
    emit(f"  [universe-export] wrote {size_bytes} bytes ({ARTIFACT_FORMAT})")
    return {
        "artifact": str(dest),
        "bytes": size_bytes,
        "format": ARTIFACT_FORMAT,
        "org": org_slug,
    }


def _org_slug(dsn: str) -> str:
    """The universe's org identity-card slug (also proves DB liveness)."""
    import psycopg

    from yoke_core.domain import db_backend

    try:
        conn = db_backend.connect_psycopg(dsn)
    except psycopg.OperationalError as exc:
        raise UniverseExportError(
            f"could not connect to the universe database: {exc}. If the "
            "embedded Postgres is stopped, `yoke local-postgres start` "
            "brings it up."
        ) from exc
    try:
        with conn:
            row = conn.execute(
                "SELECT slug FROM organizations ORDER BY id LIMIT 1"
            ).fetchone()
    except psycopg.errors.UndefinedTable:
        row = None
    finally:
        conn.close()
    if row is None or not str(row[0] or "").strip():
        raise UniverseExportError(
            "the connected database carries no organization identity card, "
            "so it does not look like a bootstrapped Yoke universe "
            "(`yoke init --local` births one)"
        )
    return str(row[0]).strip()


def _resolve_destination(
    out: Optional[Union[str, Path]], org_slug: str,
) -> Path:
    """Route ``out`` to the artifact path (see :func:`export_universe`).

    The trailing-separator check reads the raw text because ``Path``
    normalizes the separator away; without it a not-yet-created
    ``--out ~/backups/`` would silently become a file named ``backups``.
    """
    if out is None:
        return Path.cwd() / default_artifact_name(org_slug)
    raw = os.fspath(out)
    target = Path(raw).expanduser()
    if raw.endswith(("/", os.sep)) or target.is_dir():
        target.mkdir(parents=True, exist_ok=True)
        return target / default_artifact_name(org_slug)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


__all__ = [
    "ARTIFACT_FORMAT",
    "ARTIFACT_SUFFIX",
    "DEFAULT_EXPORT_TIMEOUT_S",
    "EXPORT_TIMEOUT_SETTING",
    "UniverseExportError",
    "default_artifact_name",
    "export_universe",
    "resolve_export_dsn",
]
