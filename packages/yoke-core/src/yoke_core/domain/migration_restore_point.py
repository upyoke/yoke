"""Where a database lands if applying its pending migrations goes wrong.

One policy — never apply a destructive migration without a named restore
point — realized three ways, because the substrate differs and no single
mechanism is right everywhere:

- a **fleet** takes one managed-Postgres snapshot before it rolls anything.
  A dump per tenant taken at container boot would run past the deploy health
  window on a large tenant, and it would write into the container about to be
  replaced; the pre-roll snapshot is faster, covers every database at once,
  and survives the failure.
- a **self-hosted install** dumps onto the volume its database lives on. Worth
  stating honestly: that protects against a failed migration, which is the
  common case, and does not survive host loss. Disaster recovery stays a
  separate concern.
- a **developer machine** dumps under its Yoke state directory.

Which one applies is a property of the deployment, not something a booting
process should try to infer about itself, so it is read from configuration the
deployer already sets.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional, Tuple

from yoke_contracts.machine_config.runtime import yoke_home

from yoke_core.domain import db_backend
from yoke_core.domain.migration_apply_contract import MigrationApplyError

#: Set by a deployment that has already established a restore point covering
#: this database. The value is whatever names it to an operator in a recovery —
#: a snapshot identifier, a point-in-time window.
RESTORE_POINT_ENV = "YOKE_MIGRATION_RESTORE_POINT"

#: Set by a deployment whose database is local to the machine but whose state
#: does not live under the home directory — a self-hosted install pointing at
#: the persistent volume the database is on.
BACKUP_ROOT_ENV = "YOKE_MIGRATION_BACKUP_ROOT"

BACKUP_REASON = "pre-migration-apply"


class RestorePointRequired(MigrationApplyError):
    """Refused to apply because no restore point covers the change."""


def configured_restore_point() -> Tuple[Optional[Path], Optional[str]]:
    """Return ``(backup_root, external_restore_point)`` from the environment.

    Exactly one of the two is non-``None``. See the module docstring for which
    deployment sets which.
    """
    external = os.environ.get(RESTORE_POINT_ENV, "").strip()
    if external:
        return None, external
    configured = os.environ.get(BACKUP_ROOT_ENV, "").strip()
    if configured:
        return Path(configured), None
    return yoke_home() / "backups", None


def establish(
    conn: Any,
    *,
    backup_root: Optional[Path],
    backup_target_dsn: Optional[str] = None,
    external_restore_point: Optional[str],
) -> str:
    """Return the identifier of a restore point covering *conn*.

    Takes the dump itself when given a ``backup_root`` and an explicit
    caller-resolved ``backup_target_dsn``; accepts an already established one
    when given ``external_restore_point``. The target is never recovered from
    ambient Yoke state: this connection may belong to any project's declared
    authority, so only its caller can name the matching dump target safely.

    Refusing when neither restore-point form is present is the policy, not a
    precaution: nothing destructive runs without a named way back.
    """
    external = None
    if external_restore_point is not None:
        external = str(external_restore_point).strip()
        if not external:
            raise RestorePointRequired(
                "external_restore_point must be a non-empty identifier"
            )
    if external and backup_root:
        raise RestorePointRequired(
            "supply either backup_root or external_restore_point, not both; "
            "two restore points means neither is authoritative in a recovery"
        )
    if external:
        return external
    if backup_root is None:
        raise RestorePointRequired(
            "refusing to apply pending migrations with no restore point: pass "
            "backup_root to dump before applying, or external_restore_point to "
            "name a snapshot already taken"
        )
    if not backup_target_dsn or not backup_target_dsn.strip():
        raise RestorePointRequired(
            "backup_root requires backup_target_dsn resolved for the same "
            "authoritative database as conn; ambient Yoke DSN resolution is "
            "not a safe cross-project dump target"
        )
    if not db_backend.connection_is_postgres(conn):
        raise RestorePointRequired(
            "restore-point dumps are Postgres-only; a non-Postgres authoritative "
            "database needs its own explicit restore contract"
        )
    from yoke_core.domain.migration_apply_targets import dump_postgres_to_directory

    return dump_postgres_to_directory(
        backup_target_dsn, BACKUP_REASON, Path(backup_root)
    )


__all__ = [
    "BACKUP_REASON",
    "BACKUP_ROOT_ENV",
    "RESTORE_POINT_ENV",
    "RestorePointRequired",
    "configured_restore_point",
    "establish",
]
