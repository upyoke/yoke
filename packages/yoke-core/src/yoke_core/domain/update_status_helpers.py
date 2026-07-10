"""Helper functions for epic-task status mutation orchestration.

Validation helpers, dry-run checks, transition utilities, constants/lookup
tables, and guard checks used by ``update_status.py``.

GitHub side effects flow through
:mod:`yoke_core.domain.gh_rest_transport` (bearer-token REST). Callers
dispatch REST calls directly via the helpers in
``update_status_github_sync`` / ``update_status_epic_checkbox``.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO

from yoke_core.domain import db_backend, gh_retry
from yoke_core.domain.project_github_auth import (
    InvalidToken,
    ProjectGithubAuthError,
)

# ---------------------------------------------------------------------------
# Constants / lookup tables
# ---------------------------------------------------------------------------

RETRY_DELAYS = (5, 15)
RETRY_MARKERS = tuple(
    marker for marker, _case_sensitive in gh_retry.RETRY_STDERR_MATCHERS
)


# ---------------------------------------------------------------------------
# Path / config helpers
# ---------------------------------------------------------------------------


def _repo_root() -> Path:
    yoke_root = os.environ.get("YOKE_ROOT")
    if yoke_root:
        try:
            from yoke_core.domain.worktree import resolve_yoke_root

            return Path(
                resolve_yoke_root(yoke_root_env=yoke_root)
            ).parent
        except (ImportError, RuntimeError):
            pass

    try:
        from yoke_core.domain.worktree import resolve_main_root

        return Path(resolve_main_root(cwd=os.getcwd()))
    except (ImportError, RuntimeError):
        pass

    from yoke_core.api.repo_root import find_repo_root

    return find_repo_root(Path(__file__))


def _yoke_root() -> Path:
    try:
        from yoke_core.domain.worktree import resolve_yoke_root

        return Path(
            resolve_yoke_root(yoke_root_env=os.environ.get("YOKE_ROOT") or None)
        )
    except (ImportError, RuntimeError):
        return _repo_root() / ".yoke"


# ---------------------------------------------------------------------------
# Timestamp / dry-run helpers
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _is_dry_run() -> bool:
    return os.environ.get("YOKE_DRY_RUN", "0") == "1"


# ---------------------------------------------------------------------------
# GitHub auth / project resolution
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# DB lookup helpers
# ---------------------------------------------------------------------------


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _resolve_repo_for_epic(
    conn: Any,
    epic_id: str,
) -> tuple[str, str]:
    """Return ``(project, github_repo)`` for the parent item of an epic."""
    p = _p(conn)
    try:
        row = conn.execute(
            f"""SELECT COALESCE(p.slug, ''), COALESCE(p.github_repo, '')
               FROM items i
               LEFT JOIN projects p ON p.id = i.project_id
               WHERE CAST(i.id AS TEXT) = CAST({p} AS TEXT)
               LIMIT 1""",
            (str(epic_id),),
        ).fetchone()
    except db_backend.operational_error_types(conn):
        # Graceful degradation when projects table doesn't exist (e.g. tests)
        return "", ""
    if row is None:
        return "", ""
    return str(row[0] or ""), str(row[1] or "")


def _repo_args(repo: str) -> list[str]:
    return ["-R", repo] if repo else []


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------


def _emit_event(
    name: str,
    *,
    epic_id: str,
    task_num: str,
    context_json: str = "{}",
    severity: str = "WARN",
    outcome: str = "failed",
) -> None:
    """Emit a task github-sync event via the native Python emitter."""
    try:
        from yoke_core.domain.events import emit_event as _native_emit
        try:
            context_obj = json.loads(context_json)
        except (ValueError, TypeError):
            context_obj = {"raw": context_json}
        _native_emit(
            name,
            event_kind="system",
            event_type="github_sync",
            source_type="script",
            severity=severity,
            outcome=outcome,
            item_id=f"YOK-{epic_id}",
            task_num=int(task_num) if str(task_num).isdigit() else None,
            context=context_obj,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Claim verification guard
# ---------------------------------------------------------------------------


def _verify_claim(epic_id: str, task_num: str, *, stderr: TextIO) -> None:
    """In-process claim verification.

    Replaces the former ``verify-claim.sh`` subprocess dispatch with a direct
    call to the owned ``yoke_core.domain.verify_claim`` domain module.
    """
    from yoke_core.domain import verify_claim as _verify_claim_mod

    try:
        epic_id_int = int(str(epic_id).lstrip("#"))
    except ValueError:
        return
    try:
        rc, result = _verify_claim_mod.verify(epic_id_int)
    except Exception:  # pragma: no cover - degrade open on domain errors
        return

    if rc != 0:
        reason = (result or {}).get("reason") or "claim verification failed"
        print(
            f"Error: Claim verification denied for epic {epic_id} task {task_num}: {reason}",
            file=stderr,
        )
        print(
            f"  Claim first: python3 -m yoke_core.api.service_client claim-work --item YOK-{epic_id}",
            file=stderr,
        )
        print(
            "  Incident recovery: python3 -m yoke_core.engines.repair_status (emits audit events)",
            file=stderr,
        )
        print(
            "  Audit bypass: set YOKE_CLAIM_BYPASS=<source> for sanctioned system transitions",
            file=stderr,
        )
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# History insert (event emission)
# ---------------------------------------------------------------------------


def _history_insert(
    epic_id: str,
    task_num: str,
    from_status: str,
    to_status: str,
    note: str,
) -> None:
    """Insert a task status-change history row via the native Python emitter."""
    ctx: dict = {"from_status": from_status, "to_status": to_status}
    if note:
        ctx["note"] = note

    try:
        from yoke_core.domain.events import emit_event as _native_emit
        _native_emit(
            "TaskStatusChanged",
            event_kind="lifecycle",
            event_type="task_status_change",
            source_type="system",
            severity="STATUS",
            outcome="completed",
            item_id=f"YOK-{epic_id}",
            task_num=int(task_num) if str(task_num).isdigit() else None,
            context=ctx,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Board rebuild
# ---------------------------------------------------------------------------


def _rebuild_board(out: TextIO = sys.stderr) -> None:
    """Trigger board rebuild (in-process, zero-shell).

    Best-effort: the board is a generated client-local view, so a rebuild
    failure (no checkout, schema/data hiccup, lock contention) is non-fatal
    to the status transition — it never propagates. A no-checkout environment
    (a server-side https epic-task update with no repo) gets a clearer
    advisory instead of a silent skip.
    """
    from yoke_core.domain import rebuild_board as _rebuild_board_mod

    try:
        repo_root = _repo_root()
    except (RuntimeError, FileNotFoundError) as exc:
        print(f"[no-checkout] Skipping board rebuild: {exc}", file=out)
        return
    try:
        _rebuild_board_mod.rebuild(repo_arg=str(repo_root))
    except Exception:
        pass


__all__ = [
    "InvalidToken",
    "ProjectGithubAuthError",
    "RETRY_DELAYS",
    "RETRY_MARKERS",
    "_emit_event",
    "_history_insert",
    "_is_dry_run",
    "_now_iso",
    "_rebuild_board",
    "_repo_args",
    "_repo_root",
    "_resolve_repo_for_epic",
    "_yoke_root",
    "_verify_claim",
]
