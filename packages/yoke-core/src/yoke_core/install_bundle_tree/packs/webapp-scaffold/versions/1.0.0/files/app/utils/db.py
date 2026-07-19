"""Database connection and transaction helpers for {{project_display_name}}."""

import os
import sqlite3
from contextlib import contextmanager

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
