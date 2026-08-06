"""Database connection and transaction helpers for {{project_display_name}}."""

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import uuid

# Resolve paths relative to the app root (parent of utils/)
APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("APP_DATA_DIR", os.path.join(APP_DIR, "data"))
DEFAULT_DB_PATH = os.path.join(DATA_DIR, "app.db")


def get_db_path():
    """Return the DB path, respecting APP_DB_PATH env var for testing."""
    return os.environ.get("APP_DB_PATH", DEFAULT_DB_PATH)


def get_connection(db_path=None):
    """Open a SQLite connection with standard settings."""
    path = db_path or get_db_path()
    # check_same_thread=False is required for FastAPI: get_db (dependency)
    # and the endpoint body may execute in different threadpool threads,
    # which raises sqlite3.ProgrammingError on connections bound to one
    # thread. Each request creates its own conn and closes it in finally,
    # so no connection is ever shared across concurrent requests.
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.row_factory = sqlite3.Row
    return conn


def preview_migration_work(conn, history):
    """Read pending membership and ledger adoption without mutating either."""
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(schema_version)")
    }
    if not columns:
        return tuple(history), True
    name_expr = "migration_name" if "migration_name" in columns else "NULL"
    version_expr = "version" if "version" in columns else "NULL"
    digest_expr = "content_sha256" if "content_sha256" in columns else "NULL"
    rows = conn.execute(
        f"SELECT {name_expr}, {version_expr}, {digest_expr} FROM schema_version"
    ).fetchall()
    by_sequence = {entry.sequence: entry.name for entry in history}
    applied = set()
    adoption = "migration_name" not in columns or "content_sha256" not in columns
    for name, version, digest in rows:
        if name:
            applied.add(str(name))
        else:
            adoption = True
            if version is not None and int(version) in by_sequence:
                applied.add(by_sequence[int(version)])
        if not digest:
            adoption = True
    pending = tuple(entry for entry in history if entry.name not in applied)
    ledger_change = adoption or "minimum_serving_version" not in columns
    return pending, ledger_change


def establish_migration_restore_point(conn, pending) -> str:
    """Publish a verified WAL-consistent backup without a permissive window."""
    database = next(
        (row[2] for row in conn.execute("PRAGMA database_list") if row[1] == "main"),
        "",
    )
    if not database:
        raise RuntimeError("Cannot establish a durable restore point for this database")
    source = Path(database).resolve()
    backup_dir = Path(os.environ.get(
        "APP_MIGRATION_BACKUP_DIR", source.parent / "migration-backups",
    ))
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup_dir.chmod(0o700)
    span = (
        f"{pending[0].name}--{pending[-1].name}"
        if pending else "ledger-adoption"
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / (
        f"{source.stem}-before-{span}-{stamp}-{uuid.uuid4().hex[:12]}.db"
    )
    partial = target.with_suffix(".db.partial")
    descriptor = os.open(partial, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(descriptor)
    backup = None
    try:
        backup = sqlite3.connect(partial)
        conn.backup(backup)
        if backup.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("SQLite restore-point integrity check failed")
        backup.close()
        backup = None
        with partial.open("rb") as stream:
            os.fsync(stream.fileno())
        os.replace(partial, target)
        directory_descriptor = os.open(backup_dir, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        return str(target)
    except Exception:
        if backup is not None:
            backup.close()
        partial.unlink(missing_ok=True)
        target.unlink(missing_ok=True)
        raise


@contextmanager
def transaction(conn):
    """Context manager for an exclusive transaction. Rolls back on error."""
    conn.execute("BEGIN EXCLUSIVE")
    try:
        yield conn
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise


def dict_from_row(row):
    """Convert a sqlite3.Row to a plain dict."""
    if row is None:
        return None
    return dict(row)


def rows_to_dicts(rows):
    """Convert a list of sqlite3.Row to a list of dicts."""
    return [dict(r) for r in rows]
