"""Event-emission rate and stray-DB health checks.

Owns:

- ``hc_event_emission_rate`` — events-per-active-session sanity check.
- ``hc_stray_db`` — stray ``yoke.db`` files at repo root or under
  ``.worktrees/<branch>/{yoke,data,runtime}/``.

Yoke's control-plane authority is Postgres, so no ``yoke.db`` file is
ever read as control-plane state. Any on-disk ``yoke.db`` is therefore an
unexpected artifact — typically a stale or buggy code path bootstrapping an
empty SQLite file from a worktree cwd. ``hc_stray_db`` is detection-only:
0-byte strays are safe to auto-delete under ``--fix``; non-empty strays are
left for operator review (never auto-deleted), and there is no authoritative
``data/yoke.db`` to migrate their contents into.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from yoke_core.domain.db_helpers import query_scalar
from yoke_core.domain.time_sql import now_sql

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


__all__ = (
    "hc_event_emission_rate",
    "hc_stray_db",
    "_find_worktree_stray_dbs",
)


def _find_worktree_stray_dbs(main_root: Path) -> List[Path]:
    """Return stray worktree-local ``yoke.db`` files under *main_root*.

    Checks the legacy ``yoke/`` subdirectory plus the ``data/`` and
    ``runtime/`` subdirectories within each linked worktree. A linked
    worktree is a code-execution surface, never a Yoke control plane, so
    any ``yoke.db`` there is a stray artifact an operator should review.
    """
    worktrees_dir = main_root / ".worktrees"
    if not worktrees_dir.is_dir():
        return []
    strays: List[Path] = []
    # Check both legacy (yoke/) and current (data/, runtime/) stray locations.
    stray_subdirs = ("yoke", "data", "runtime")
    for branch_dir in sorted(worktrees_dir.iterdir()):
        if not branch_dir.is_dir():
            continue
        for subdir in stray_subdirs:
            candidate = branch_dir / subdir / "yoke.db"
            if candidate.is_file():
                strays.append(candidate)
    return strays


def hc_event_emission_rate(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-event-emission-rate: Event emission rate."""
    if not _base._table_exists(conn, "events"):
        rec.record("HC-event-emission-rate", "Event emission rate", "PASS",
                    "events table not present, skipping")
        return

    # Check if any sessions ran in the past 24h
    session_activity = 0
    if _base._table_exists(conn, "epic_dispatch_chains"):
        v = query_scalar(
            conn,
            "SELECT COUNT(*) FROM epic_dispatch_chains "
            f"WHERE last_updated >= {now_sql(offset_days=-1)}",
        )
        session_activity += int(v) if v else 0
    if _base._table_exists(conn, "shepherd_verdicts"):
        v = query_scalar(
            conn,
            "SELECT COUNT(*) FROM shepherd_verdicts "
            f"WHERE created_at >= {now_sql(offset_days=-1)}",
        )
        session_activity += int(v) if v else 0

    if session_activity == 0:
        rec.record("HC-event-emission-rate", "Event emission rate", "PASS",
                    "No sessions in 24h, emission rate check skipped")
        return

    event_count = query_scalar(
        conn,
        f"SELECT COUNT(*) FROM events WHERE created_at >= {now_sql(offset_days=-1)}",
    )
    count = int(event_count) if event_count else 0
    if count == 0:
        rec.record("HC-event-emission-rate", "Event emission rate", "WARN",
                    "0 events emitted in 24h despite active sessions")
    else:
        rec.record("HC-event-emission-rate", "Event emission rate", "PASS",
                    f"{count} events emitted in past 24h")


def hc_stray_db(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """HC-stray-db: Stray yoke.db at repo root or under ``.worktrees/*``.

    Yoke's control-plane authority is Postgres; no ``yoke.db`` file is
    ever read as control-plane state. Any on-disk ``yoke.db`` — at the
    repo root or under ``.worktrees/<branch>/{yoke,data,runtime}/`` — is
    therefore an unexpected artifact, typically a stale or buggy code path
    bootstrapping an empty SQLite file from a worktree cwd. 0-byte strays
    are safe to auto-delete under ``--fix``; non-empty strays are left for
    operator review (never auto-deleted), and there is no authoritative
    ``data/yoke.db`` to migrate their contents into.
    """
    repo_root = _base._resolve_repo_root()
    if not repo_root:
        rec.record("HC-stray-db", "Stray yoke.db locations", "PASS", "")
        return

    # Prefer main-repo root so the scan is authoritative even when doctor
    # runs from within a linked worktree.
    main_root_str = _base._resolve_main_root() or repo_root
    main_root = Path(main_root_str)

    empty_issues: List[str] = []
    nonempty_issues: List[str] = []

    root_stray = main_root / "yoke.db"
    if root_stray.is_file():
        size = root_stray.stat().st_size
        if size == 0:
            empty_issues.append(
                f"- {root_stray}: stray yoke.db at repo root "
                "(0 bytes — safe to delete)"
            )
        else:
            nonempty_issues.append(
                f"- {root_stray}: stray yoke.db at repo root "
                f"({size} bytes) — not Yoke control-plane state "
                "(Postgres is authoritative); review and remove"
            )

    for stray in _find_worktree_stray_dbs(main_root):
        size = stray.stat().st_size
        if size == 0:
            empty_issues.append(
                f"- {stray}: stray worktree-local yoke.db "
                "(0 bytes — safe to delete; a worktree is a code surface, "
                "never a Yoke control plane)"
            )
        else:
            nonempty_issues.append(
                f"- {stray}: stray worktree-local yoke.db "
                f"({size} bytes) — not Yoke control-plane state "
                "(Postgres is authoritative); review and remove"
            )

    issues = empty_issues + nonempty_issues

    if not issues:
        rec.record("HC-stray-db", "Stray yoke.db locations", "PASS", "")
        return

    if nonempty_issues:
        # A non-empty stray is never auto-deleted, not even with --fix: the
        # 2026-04-11 incident proved silent cleanup can destroy unrecoverable
        # session telemetry (see ouroboros/patterns.md). Yoke's control
        # plane is Postgres, so there is no authoritative data/yoke.db to
        # merge a stray into — the operator reviews the file and removes it.
        detail_lines = list(issues)
        detail_lines.append("")
        detail_lines.append("Remediation for non-empty strays:")
        detail_lines.append(
            "  1. Yoke's control-plane authority is Postgres — this "
            "SQLite file is not Yoke state and is never read by the "
            "control plane."
        )
        detail_lines.append(
            "  2. If you need to confirm nothing important was captured, "
            "inspect only the stray artifact with a SQLite file inspector; "
            "this is historical/stray-file review, not a Yoke runtime "
            "authority check."
        )
        detail_lines.append(
            "  3. Remove the stray file once reviewed. Postgres is the "
            "control-plane authority; no on-disk SQLite file holds Yoke "
            "state."
        )
        rec.record(
            "HC-stray-db",
            "Stray yoke.db locations",
            "WARN",
            "\n".join(detail_lines),
        )
        return

    # All strays are 0-byte. Safe to delete automatically with --fix.
    if getattr(args, "fix", False):
        removed = 0
        for line in empty_issues:
            # line format: "- <path>: ..."
            path_str = line.split(":", 1)[0].lstrip("- ").strip()
            try:
                Path(path_str).unlink()
                removed += 1
            except OSError:
                pass
        if removed:
            rec.record(
                "HC-stray-db",
                "Stray yoke.db locations",
                "PASS",
                f"- --fix: removed {removed} 0-byte stray yoke.db file(s)",
            )
            return

    rec.record(
        "HC-stray-db",
        "Stray yoke.db locations",
        "WARN",
        "\n".join(issues),
    )
