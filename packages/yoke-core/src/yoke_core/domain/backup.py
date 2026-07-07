"""Retired local ``yoke.db`` backup command.

Yoke authority is Postgres-native. This module is retained only so legacy
operator/debug invocations fail with an explicit retirement message instead of
constructing or requiring ``data/yoke.db``.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from yoke_core.domain import db_helpers
from yoke_core.domain.worktree import resolve_named_path

RETIRED_BACKUP_MESSAGE = (
    "SQLite yoke.db file backups are retired. Yoke authority is Postgres; "
    "use the Postgres-native migration rollback backup path instead."
)
DEFAULT_RETIRED_BACKUP_MAX_COUNT = 20

_USAGE = """\
Usage: backup <mode> [options]

Modes:
  backup <reason>       Retired; fails without creating a file backup
  periodic              Retired; fails without creating a file backup
  prune                 Prune old retired yoke.db backup residue
  list                  List existing retired yoke.db backup residue
  latest                Print path to most recent retired backup residue

Options:
  --max-count N         Override retired-residue retention cap (default: 20)
  --staleness-hours N   Accepted for legacy callers; ignored by retired modes
  --db PATH             Accepted for legacy callers; ignored by retired modes
  --backup-dir PATH     Override backup residue directory
  --no-s3               Accepted for legacy callers; S3 backup upload is retired
  --project PROJECT     Accepted for legacy callers; S3 backup upload is retired
"""


class RetiredBackupError(RuntimeError):
    """Raised when a caller tries to create a retired SQLite file backup."""


def _cli_error(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _backup_reason_usage(prefix: str) -> str:
    return (
        f"{prefix}\n"
        "Usage: backup backup <reason>\n"
        "       backup backup --reason <reason>\n"
        "  Allowed format: alphanumeric characters, hyphens, underscores, and dots [A-Za-z0-9_.-]\n"
        "  Example:        backup backup pre-migration"
    )


def _resolve_db_path() -> str:
    """Retained compatibility guard for callers that still ask for a DB path."""
    return db_helpers.resolve_db_path()


def _resolve_yoke_root(db_path: str) -> str:
    return os.path.dirname(db_path)


def _default_backup_dir() -> str:
    return resolve_named_path("backups", cwd=str(Path.cwd()))


def _sanitize_reason(raw: str) -> str:
    """Sanitize a reason string into a valid slug."""
    slug = re.sub(r"[ :\\/]", "-", raw)
    slug = re.sub(r"['\"]", "", slug)
    slug = re.sub(r"[^A-Za-z0-9_.\-]", "", slug)
    slug = re.sub(r"-+", "-", slug)
    slug = slug.strip("-")
    return slug


def list_backups(backup_dir: str) -> List[str]:
    """List retired backup residue files sorted newest first."""
    if not os.path.isdir(backup_dir):
        return []
    files = []
    for f in os.listdir(backup_dir):
        if f.startswith("yoke.db.") and f.endswith(".sqlite3"):
            files.append(os.path.join(backup_dir, f))
    return sorted(files, reverse=True)


def newest_backup(backup_dir: str) -> Optional[str]:
    backups = list_backups(backup_dir)
    return backups[0] if backups else None


def create_backup(db_path: str, backup_dir: str, reason: str) -> str:
    """Fail closed: creating SQLite ``yoke.db`` file backups is retired."""
    reason = _sanitize_reason(reason)
    if not reason:
        raise ValueError(
            _backup_reason_usage("backup reason is empty after sanitization.")
        )
    raise RetiredBackupError(RETIRED_BACKUP_MESSAGE)


def prune_backups(backup_dir: str, max_count: int) -> int:
    """Prune old retired backup residue, return count of pruned files."""
    backups = list_backups(backup_dir)
    pruned = 0
    for i, path in enumerate(backups):
        if i >= max_count:
            os.remove(path)
            pruned += 1
    return pruned


def is_stale(backup_dir: str, staleness_hours: int) -> bool:
    """Check if newest retired backup residue is older than the window."""
    path = newest_backup(backup_dir)
    if not path:
        return True

    basename = os.path.basename(path)
    m = re.match(r"yoke\.db\.(\d{8}-\d{6})\.", basename)
    if not m:
        return True

    ts_str = m.group(1)
    try:
        backup_time = datetime.strptime(ts_str, "%Y%m%d-%H%M%S").replace(
            tzinfo=timezone.utc
        )
    except ValueError:
        return True

    age_hours = (datetime.now(timezone.utc) - backup_time).total_seconds() / 3600
    return age_hours >= staleness_hours


def main(argv: Optional[List[str]] = None) -> None:
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        _cli_error(_USAGE)

    mode = None
    reason = None
    max_count = None
    backup_dir = None
    missing_reason_flag = False

    i = 0
    while i < len(args):
        a = args[i]
        if a == "backup":
            mode = "backup"
            i += 1
            if i < len(args) and not args[i].startswith("--"):
                reason = args[i]
                i += 1
            elif i < len(args) and args[i] == "--reason":
                i += 1
                if i < len(args) and not args[i].startswith("--"):
                    reason = args[i]
                    i += 1
                else:
                    missing_reason_flag = True
        elif a in ("periodic", "prune", "list", "latest"):
            mode = a
            i += 1
        elif a == "--max-count" and i + 1 < len(args):
            max_count = int(args[i + 1])
            i += 2
        elif a == "--staleness-hours" and i + 1 < len(args):
            i += 2
        elif a == "--db" and i + 1 < len(args):
            i += 2
        elif a == "--backup-dir" and i + 1 < len(args):
            backup_dir = args[i + 1]
            i += 2
        elif a == "--no-s3":
            i += 1
        elif a == "--project" and i + 1 < len(args):
            i += 2
        else:
            _cli_error(f"Error: Unknown argument '{a}'")

    if not mode:
        _cli_error(_USAGE)

    if mode == "backup":
        if not reason or missing_reason_flag:
            _cli_error(
                _backup_reason_usage("Error: backup mode requires a reason slug")
            )
        try:
            create_backup("", backup_dir or "", reason)
        except (ValueError, RetiredBackupError) as e:
            _cli_error(f"Error: {e}")

    if mode == "periodic":
        _cli_error(f"Error: {RETIRED_BACKUP_MESSAGE}")

    if not backup_dir:
        backup_dir = _default_backup_dir()

    if max_count is None:
        max_count = DEFAULT_RETIRED_BACKUP_MAX_COUNT

    if mode == "prune":
        pruned = prune_backups(backup_dir, max_count)
        if pruned:
            print(f"Pruned {pruned} old backup(s), kept {max_count}", file=sys.stderr)

    elif mode == "list":
        for path in list_backups(backup_dir):
            print(path)

    elif mode == "latest":
        nb = newest_backup(backup_dir)
        if nb:
            print(nb)


if __name__ == "__main__":
    main()
