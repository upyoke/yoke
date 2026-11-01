"""Export the active universe to one self-contained portable archive.

One schema runs in every deployment mode, so moving a universe between
modes (local / self-host / hosted) is dump-and-restore; this module owns
the dump half. :func:`export_universe` produces ONE tar artifact
(:mod:`yoke_core.domain.universe_archive`) carrying the ``pg_dump``
custom-format payload and the freeze receipt that binds it — the receipt
travels inside the file, so the importer derives every verification
figure from the artifact itself instead of asking the operator.

The dump and its receipt are bound to one exported PostgreSQL snapshot:
authority watermarks are read inside the same ``REPEATABLE READ READ
ONLY`` view the dump exports, and the export refuses if the universe's
authority receipt changed while the dump ran.

Authority for this direct engine is DSN possession. Export is sanctioned when
the active machine-config connection is an unprotected Postgres connection whose
DSN this machine holds (the local universe's shape). The product CLI routes an
authenticated self-host HTTPS connection through the server-held authority and
routes hosted org admins to the dashboard's Universe portability controls. This
direct engine still refuses HTTPS connections and protected Postgres
connections. ``pg_dump`` resolves from the embedded engine's installed
binaries first, then ``PATH`` — the same rule the cluster lifecycle uses for
``initdb``/``pg_ctl``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, Optional, Union

from yoke_core.domain import universe_archive
from yoke_core.domain.universe_export_destination import (
    UniverseExportError,
    default_artifact_name,
    resolve_export_destination,
)

#: One tar carrying ``universe.dump`` + ``freeze-receipt.json``.
ARTIFACT_FORMAT = "universe-tar"

ARTIFACT_SUFFIX = universe_archive.ARTIFACT_SUFFIX

#: Machine-settings key capping the dump subprocess runtime.
EXPORT_TIMEOUT_SETTING = "universe_export_timeout_seconds"
DEFAULT_EXPORT_TIMEOUT_S = 600


def resolve_export_dsn() -> str:
    """The active connection's DSN when export is sanctioned, else raise.

    Sanction rule: an unprotected Postgres connection whose credentials this
    machine holds. HTTPS refuses because its server-side routing belongs to
    the product CLI, outside this direct-DSN engine. Protected Postgres
    refuses (operator-only).
    """
    from yoke_contracts.machine_config.schema import connection_is_protected
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
            "universe_export_dashboard_required: hosted sources use Prepare archive "
            "in the dashboard's Universe portability controls; self-host sources use "
            "the authenticated server export endpoint"
        )
    if connection_is_protected(env.config):
        raise UniverseExportError(
            f"the active connection {env.environment!r} is a protected "
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
    exclude_artifacts: bool = False,
    pause_source: bool = False,
    emit: Callable[[str], None] = lambda _line: None,
) -> Dict[str, Any]:
    """Export the active universe to one self-contained tar artifact.

    ``dsn=None`` resolves (and sanction-checks) the active connection; an
    explicit ``dsn`` is the injection seam for tests and operator tooling.
    ``out`` routing: ``None`` writes under the machine Yoke home exports folder; a
    trailing path separator always means a directory (created when
    missing — pass the raw string, ``Path`` drops the separator); an
    existing directory stays a directory; any other path is the target
    file. Directory targets get the default filename, which embeds the
    org slug and a UTC timestamp. Returns a payload naming the artifact
    path, size, org slug, archive format, and the dump payload's SHA-256
    (also recorded inside the artifact's freeze receipt).
    """
    from yoke_core.domain.universe_snapshot_archive import snapshot_archive

    resolved_dsn = dsn if dsn is not None else resolve_export_dsn()
    # Prove destination access before stopping writers; the snapshot names the org.
    resolve_export_destination(out, "universe")
    _start_own_universe(resolved_dsn, emit)
    from yoke_core.domain import universe_source_pause

    if pause_source:
        with (
            universe_source_pause.operation(resolved_dsn),
            universe_source_pause.pause_owner(),
        ):
            universe_source_pause.pause(resolved_dsn)
            export_dsn, identity = universe_source_pause.export_source(resolved_dsn)
            emit("Source paused; run `yoke universe resume` when it may write again.")
            try:
                return snapshot_archive(
                    dsn=export_dsn,
                    source_identity=identity,
                    out=out,
                    writers_stopped=True,
                    include_artifacts=not exclude_artifacts,
                    emit=emit,
                )
            except UniverseExportError as exc:
                raise UniverseExportError(
                    f"{exc}; source stays paused; run `yoke universe resume` "
                    "when it may write again"
                ) from exc
    return snapshot_archive(
        dsn=resolved_dsn,
        out=out,
        writers_stopped=False,
        include_artifacts=not exclude_artifacts,
        emit=emit,
    )


def _start_own_universe(dsn: str, emit: Callable[[str], None]) -> None:
    """Start this machine's stopped embedded cluster before reading it."""
    from yoke_core.domain import local_universe, local_universe_autostart
    from yoke_core.domain.local_universe_convergence import serves_own_universe

    if not serves_own_universe(dsn):
        return
    try:
        local_universe_autostart.ensure_running(emit=emit)
    except local_universe.LocalUniverseError as exc:
        raise UniverseExportError(str(exc)) from exc


def resume_universe() -> dict:
    from yoke_core.domain import universe_source_pause

    return universe_source_pause.resume(resolve_export_dsn())


def estimate_universe(*, exclude_artifacts: bool = False) -> dict:
    """Estimate the active local export through the same authority boundary."""
    from yoke_core.domain.universe_artifact_transfer import (
        estimate_universe as estimate,
    )

    try:
        return estimate(exclude_artifacts=exclude_artifacts)
    except universe_archive.UniverseArchiveError as exc:
        raise UniverseExportError(str(exc)) from exc


__all__ = [
    "ARTIFACT_FORMAT",
    "ARTIFACT_SUFFIX",
    "DEFAULT_EXPORT_TIMEOUT_S",
    "EXPORT_TIMEOUT_SETTING",
    "UniverseExportError",
    "default_artifact_name",
    "export_universe",
    "estimate_universe",
    "resolve_export_destination",
    "resolve_export_dsn",
]
