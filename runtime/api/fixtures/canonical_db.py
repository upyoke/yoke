"""Shared canonical DB guard for harness-driven test runs.

The retired root ``data/yoke.db`` file is no longer an ambient authority
source. This helper remains as a Python-owned refusal guard: explicit
fixture ``YOKE_DB`` values are preserved, but the helper does not discover
or export the retired root DB file path for ordinary Postgres-native test
runs.

The guard is harness-universal because it lives under ``runtime/api/fixtures``
instead of a harness-specific adapter; explicit callers can use the same
Python surface without shell choreography.

The resolver delegates to :func:`yoke_core.domain.worktree.resolve_named_path`
with the ``db`` mode only to detect the retired path refusal through the same
operator-facing CLI logic.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional


YOKE_DB_ENV = "YOKE_DB"


class CanonicalDbResolutionError(RuntimeError):
    """Raised when canonical-DB resolution fails for a callsite that
    requires it (e.g., explicit operator-facing surfaces). The ambient
    test path treats failure as a no-op so non-worktree environments are
    unaffected."""


def resolve_canonical_yoke_db() -> Optional[str]:
    """Return a legacy canonical DB path only when explicitly still supported.

    Delegates to :func:`yoke_core.domain.worktree.resolve_named_path` so the
    resolution mirrors the operator-facing CLI ``python3 -m
    yoke_core.domain.worktree paths db``. ``ValueError`` and ``RuntimeError``
    are swallowed because Postgres-native checkouts intentionally refuse the
    retired root DB file path.
    """
    try:
        from yoke_core.domain.worktree import resolve_named_path
    except ImportError:
        return None
    try:
        return resolve_named_path("db")
    except (RuntimeError, ValueError):
        return None


def export_canonical_yoke_db() -> Optional[str]:
    """Preserve explicit ``YOKE_DB`` and avoid ambient root DB export.

    The function is idempotent: a pre-existing non-retired ``YOKE_DB`` is
    never overwritten, so tests that intentionally point ``YOKE_DB`` at a
    fixture DB continue to work. When unset, the environment stays unchanged.
    """
    existing = os.environ.get(YOKE_DB_ENV)
    if existing:
        if sqlite_authority_retired_for_path(existing):
            return None
        return existing
    return None


def sqlite_authority_retired_for_path(db_path: str) -> bool:
    """Return true when *db_path* belongs to a Postgres-connected checkout."""
    try:
        from yoke_core.domain import yoke_connected_env
        from yoke_core.domain.yoke_connected_env_sqlite import (
            retired_yoke_db_path_reason,
        )

        env = yoke_connected_env.load_active(Path(db_path).expanduser().parent.parent)
        return retired_yoke_db_path_reason(env, db_path) is not None
    except Exception:
        return False


def assert_canonical_yoke_db() -> str:
    """Stricter variant: require an explicit non-retired fixture DB path.

    Useful for harness wrappers and operator-facing pre-pytest setup paths
    that must fail loudly with an actionable message instead of silently
    falling back to retired root SQLite authority.
    """
    existing = os.environ.get(YOKE_DB_ENV)
    if existing:
        if sqlite_authority_retired_for_path(existing):
            raise CanonicalDbResolutionError(
                "The canonical root Yoke DB file is retired for this "
                "connected Postgres checkout; do not export YOKE_DB."
            )
        return existing
    raise CanonicalDbResolutionError(
        "Canonical root Yoke DB file authority is retired. Use Postgres "
        "authority through YOKE_PG_DSN / YOKE_PG_DSN_FILE or set "
        "YOKE_DB only to an explicit isolated fixture DB. Detector: "
        "python3 -m yoke_core.domain.worktree paths db."
    )


def main(argv: Optional[list] = None) -> int:
    """CLI surface: print the resolved DB path or exit 1 with diagnostic."""
    args = list(argv if argv is not None else sys.argv[1:])
    strict = "--strict" in args
    if strict:
        try:
            print(assert_canonical_yoke_db())
            return 0
        except CanonicalDbResolutionError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    resolved = export_canonical_yoke_db()
    if resolved:
        print(resolved)
        return 0
    print(
        "Error: canonical root Yoke DB file authority is retired. "
        "Use YOKE_PG_DSN / YOKE_PG_DSN_FILE, or set YOKE_DB only "
        "to an explicit isolated fixture DB.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
