"""Event-family liveness and stray-DB health checks.

Owns:

- ``hc_event_family_liveness`` — durable activity paired with expected events.
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

from dataclasses import dataclass
from pathlib import Path
from typing import List

from yoke_core.domain.db_helpers import query_scalar
from yoke_core.domain.time_sql import now_sql

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector
from yoke_core.engines.doctor_tree_scan import list_directory


__all__ = (
    "EVENT_FAMILY_LIVENESS_PAIRS",
    "hc_event_family_liveness",
    "hc_stray_db",
    "_find_worktree_stray_dbs",
)


EVENT_FAMILY_JOIN_WINDOW_DAYS = 7


@dataclass(frozen=True)
class EventFamilyLivenessPair:
    """One durable activity source and the telemetry it should produce."""

    durable_table: str
    expected_event: str
    activity_column: str
    join_window_days: int


EVENT_FAMILY_LIVENESS_PAIRS = (
    EventFamilyLivenessPair(
        "items", "ItemStatusChanged", "updated_at", EVENT_FAMILY_JOIN_WINDOW_DAYS
    ),
    EventFamilyLivenessPair(
        "qa_requirements", "QARequirementCreated", "created_at",
        EVENT_FAMILY_JOIN_WINDOW_DAYS,
    ),
    EventFamilyLivenessPair(
        "qa_runs", "QARunCompleted", "completed_at", EVENT_FAMILY_JOIN_WINDOW_DAYS
    ),
    EventFamilyLivenessPair(
        "harness_sessions", "HarnessSessionStarted", "offered_at",
        EVENT_FAMILY_JOIN_WINDOW_DAYS,
    ),
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
    for branch_dir in list_directory(worktrees_dir):
        if not branch_dir.is_dir():
            continue
        for subdir in stray_subdirs:
            candidate = branch_dir / subdir / "yoke.db"
            if candidate.is_file():
                strays.append(candidate)
    return strays


def hc_event_family_liveness(conn, args: DoctorArgs, rec: RecordCollector) -> None:
    """Warn when recent durable activity has no matching event family."""
    check_id = "HC-event-family-liveness"
    check_name = "Event family liveness"
    events_available = _base._table_exists(conn, "events")
    checked = 0
    active = 0
    dark_families: list[str] = []

    for pair in EVENT_FAMILY_LIVENESS_PAIRS:
        if not _base._table_exists(conn, pair.durable_table):
            continue
        if not _base._column_exists(
            conn, pair.durable_table, pair.activity_column
        ):
            continue
        checked += 1
        cutoff = now_sql(offset_days=-pair.join_window_days)
        durable_count = int(
            query_scalar(
                conn,
                f"SELECT COUNT(*) FROM {pair.durable_table} "
                f"WHERE {pair.activity_column} IS NOT NULL "
                f"AND {pair.activity_column} >= {cutoff}",
            )
            or 0
        )
        if durable_count == 0:
            continue
        active += 1
        event_count = 0
        if events_available:
            event_count = int(
                query_scalar(
                    conn,
                    "SELECT COUNT(*) FROM events WHERE event_name = %s "
                    f"AND created_at >= {cutoff}",
                    (pair.expected_event,),
                )
                or 0
            )
        if event_count == 0:
            dark_families.append(
                f"- {pair.durable_table}: {durable_count} recent row(s), "
                f"0 {pair.expected_event} events"
            )

    if dark_families:
        # Initial posture is WARN; the zero-event predicate is deliberately
        # binary so rare families with no durable activity remain green.
        rec.record(
            check_id,
            check_name,
            "WARN",
            "Durable activity has no matching telemetry in the trailing "
            f"{EVENT_FAMILY_JOIN_WINDOW_DAYS}-day join window:\n"
            + "\n".join(dark_families)
            + "\nRecovery: inspect emit_event durability for each named family. "
            "Product state remains authoritative in the durable tables.",
        )
        return

    rec.record(
        check_id,
        check_name,
        "PASS",
        f"{checked} family pair(s) checked; {active} had recent durable activity",
    )


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
        try:
            size = stray.stat().st_size
        except FileNotFoundError:
            # A worktree removed between discovery and sizing is not a stray.
            continue
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
