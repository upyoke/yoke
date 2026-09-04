"""Backlog rendering, board rebuild, GitHub sync, and event helpers."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Optional, TextIO

if TYPE_CHECKING:
    from yoke_core.domain.backlog_github_body_budget import SyncMode

from yoke_core.domain.project_identity_item_ref import item_ref_for_id
from yoke_core.domain.board_rebuild_failure import record_board_rebuild_failure
from yoke_core.domain.backlog_queries import (
    _is_dry_run,
    _yoke_root,
)


# ---------------------------------------------------------------------------
# Board rebuild
# ---------------------------------------------------------------------------

def _rebuild_board(out: TextIO = sys.stderr) -> str:
    """Rebuild the generated board; return a recorded failure or ``""``."""
    from yoke_core.domain import rebuild_board as _rebuild_board_mod

    try:
        repo_root = _yoke_root().parent
    except RuntimeError as exc:
        # No checkout: hosted/self-host skip silently; local rootless still warns.
        _rebuild_board_mod.emit_no_checkout_board_skip(exc, out)
        return ""
    yoke_db = os.environ.get("YOKE_DB")
    if yoke_db:
        try:
            db_resolved = Path(yoke_db).resolve()
            root_resolved = Path(repo_root).resolve()
            db_resolved.relative_to(root_resolved)
        except (ValueError, OSError):
            print(
                f"[test-isolation] Skipping board rebuild: "
                f"YOKE_DB={yoke_db} is outside repo_root={repo_root}",
                file=out,
            )
            return ""

    try:
        result = _rebuild_board_mod.rebuild(repo_arg=str(repo_root), emit=False)
    except Exception as exc:
        return record_board_rebuild_failure(
            f"{type(exc).__name__}: {exc}",
            out,
        )
    if int(result) != 0:
        detail = getattr(result, "message", "") or f"exit code {int(result)}"
        return record_board_rebuild_failure(detail, out)
    return ""


def _maybe_rebuild_board(
    rebuild_board: bool,
    *,
    dry_run: bool = False,
    respect_global_dry_run: bool = True,
    out: TextIO = sys.stderr,
) -> str:
    """Trigger board rebuild unless suppressed by caller or dry-run mode."""
    if not rebuild_board or dry_run or (respect_global_dry_run and _is_dry_run()):
        return ""
    return _rebuild_board(out)


# ---------------------------------------------------------------------------
# Event emission
# ---------------------------------------------------------------------------

def _emit_event(
    name: str,
    item_id: int,
    context: dict,
    out: TextIO = sys.stderr,
) -> None:
    """Emit a structured lifecycle event directly via the Python emitter.

    Calls ``yoke_core.domain.events.emit_event`` in-process. Non-fatal on
    failure.
    """
    try:
        from yoke_core.domain.events import emit_event as _native_emit
    except ImportError:
        # When invoked from a deleted worktree CWD, the events
        # module may be unreachable.  Honor the non-fatal contract.
        print(
            f"Warning: {name} event emission skipped for {item_ref_for_id(item_id)}"
            " (events module unavailable)",
            file=out,
        )
        return

    envelope = _native_emit(
        name,
        event_kind="lifecycle",
        event_type="item_status_change",
        source_type="system",
        severity="STATUS",
        outcome="completed",
        item_id=int(item_id),
        context=context,
    )
    if envelope is None:
        print(
            f"Warning: {name} event emission failed for {item_ref_for_id(item_id)}",
            file=out,
        )


# ---------------------------------------------------------------------------
# GitHub sync helpers
# ---------------------------------------------------------------------------

STATUS_COMMENT_GITHUB_TIMEOUT_SECONDS = 5.0
STATUS_COMMENT_GITHUB_MAX_ATTEMPTS = 1


def _sync_item(item_id: int, out: TextIO = sys.stderr) -> str:
    """Sync item to GitHub, reporting one mirror-attempt outcome.

    Swallowing the failure here is what let a create report success while
    the issue it promised was never opened.
    """
    from yoke_core.domain import backlog_github_mirror_state as mirror

    if _is_dry_run():
        print(f"[DRY-RUN] Skipping GitHub: sync-item for {item_ref_for_id(item_id)}", file=out)
        return mirror.MIRROR_ATTEMPT_SKIPPED
    try:
        from yoke_core.domain import backlog_github_sync
        rc = backlog_github_sync.sync_item(item_id, stdout=out, stderr=out)
    except Exception as exc:
        print(f"Warning: GitHub sync failed for {item_ref_for_id(item_id)}: {exc}", file=out)
        return mirror.MIRROR_ATTEMPT_FAILED
    if int(rc or 0) == 0:
        return mirror.MIRROR_ATTEMPT_SYNCED
    return mirror.MIRROR_ATTEMPT_FAILED


def _sync_labels(item_id: int, out: TextIO = sys.stderr) -> bool:
    """Sync labels to GitHub."""
    if _is_dry_run():
        print(f"[DRY-RUN] Skipping GitHub: sync-labels for {item_ref_for_id(item_id)}", file=out)
        return True
    try:
        from yoke_core.domain import backlog_github_sync
        rc = backlog_github_sync.sync_labels(item_id, stdout=out, stderr=out)
        return rc == 0
    except Exception as exc:
        print(f"Warning: sync_labels failed for {item_ref_for_id(item_id)}: {exc}", file=out)
        return False


def _close_issue(item_id: int, out: TextIO = sys.stderr) -> bool:
    """Close GitHub issue.

    Emits ``SyncFailed(operation="state")`` on every failure branch — non-zero
    rc and broad-except — so every caller (``backlog_update_op``,
    ``backlog_close_op``, ``done_transition`` Step 8) reports a structured
    event symmetric with the body-sync path. ``/yoke resync --fix`` is the
    canonical convergence mechanism after the local mutation lands.
    """
    if _is_dry_run():
        print(f"[DRY-RUN] Skipping GitHub: close-issue for {item_ref_for_id(item_id)}", file=out)
        return True
    try:
        from yoke_core.domain import backlog_github_sync
        rc = backlog_github_sync.close_issue(item_id, stdout=out, stderr=out)
    except Exception as exc:
        print(f"Warning: close_issue failed for {item_ref_for_id(item_id)}: {exc}", file=out)
        _record_sync_failure(item_id, "state", f"close_issue raised: {exc}")
        return False
    if rc != 0:
        _record_sync_failure(item_id, "state", f"close_issue rc={rc}")
        return False
    return True


def _sync_title(item_id: int, out: TextIO = sys.stderr) -> bool:
    """Sync title to GitHub."""
    if _is_dry_run():
        print(f"[DRY-RUN] Skipping GitHub: sync-title for {item_ref_for_id(item_id)}", file=out)
        return True
    try:
        from yoke_core.domain import backlog_github_sync
        rc = backlog_github_sync.sync_title(item_id, stdout=out, stderr=out)
        return rc == 0
    except Exception as exc:
        print(f"Warning: sync_title failed for {item_ref_for_id(item_id)}: {exc}", file=out)
        return False


def _sync_frozen_label(item_id: int, value: str, out: TextIO = sys.stderr) -> bool:
    """Sync frozen label to GitHub."""
    try:
        from yoke_core.domain import backlog_github_sync
        rc = backlog_github_sync.sync_frozen_label(item_id, value, stdout=out, stderr=out)
        return rc == 0
    except Exception as exc:
        print(f"Warning: sync_frozen_label failed for {item_ref_for_id(item_id)}: {exc}", file=out)
        return False


def _sync_blocked_label(item_id: int, value: str, out: TextIO = sys.stderr) -> bool:
    """Sync blocked label to GitHub."""
    try:
        from yoke_core.domain import backlog_github_sync
        rc = backlog_github_sync.sync_blocked_label(item_id, value, stdout=out, stderr=out)
        return rc == 0
    except Exception as exc:
        print(f"Warning: sync_blocked_label failed for {item_ref_for_id(item_id)}: {exc}", file=out)
        return False


def _post_comment(
    item_id: int,
    old_status: str,
    new_status: str,
    out: TextIO = sys.stderr,
) -> bool:
    """Post status-change comment to GitHub."""
    try:
        from yoke_core.domain import backlog_github_sync
        rc = backlog_github_sync.post_comment(
            item_id,
            old_status,
            new_status,
            stdout=out,
            stderr=out,
            github_timeout_seconds=STATUS_COMMENT_GITHUB_TIMEOUT_SECONDS,
            github_max_attempts=STATUS_COMMENT_GITHUB_MAX_ATTEMPTS,
        )
        return rc == 0
    except Exception as exc:
        print(f"Warning: post_comment failed for {item_ref_for_id(item_id)}: {exc}", file=out)
        return False


def _sync_body(
    item_id: int,
    out: TextIO = sys.stderr,
    *,
    github_timeout_seconds: Optional[float] = None,
    github_max_attempts: Optional[int] = None,
) -> tuple[bool, "SyncMode | None"]:
    """Sync body to GitHub.

    Returns ``(success, mode)``:

    - ``(True, "full")`` — full body synced under budget.
    - ``(True, "compact")`` — compact mirror synced because the full body
      exceeded :data:`backlog_github_body_budget.GITHUB_BODY_BUDGET_BYTES`.
    - ``(True, None)`` — dry-run (no network mutation).
    - ``(False, None)`` — auth failure or transport failure; structured
      sync_warning is reported separately by callers.

    Dry-run returns ``(True, None)`` because no body was actually selected
    for upload; treating it as ``"full"`` would lie to consumers reading
    the mode for telemetry.
    """
    from yoke_core.domain.backlog_github_body_budget import (  # local: avoid module-load cycle
        body_exceeds_budget,
    )

    if _is_dry_run():
        print(f"[DRY-RUN] Skipping GitHub: sync-body for {item_ref_for_id(item_id)}", file=out)
        return True, None
    try:
        from yoke_core.domain import backlog_github_sync
        rc = backlog_github_sync.sync_body(
            item_id,
            stdout=out,
            stderr=out,
            github_timeout_seconds=github_timeout_seconds,
            github_max_attempts=github_max_attempts,
        )
        if rc != 0:
            return False, None
        # The high-level sync_body has already picked full vs compact and
        # written to GitHub; we recompute the mode from the rendered body
        # so consumers (execute_structured_write) can surface it cleanly.
        try:
            from yoke_core.domain.db_helpers import connect
            from yoke_core.domain.render_body import build_body
            from yoke_core.domain.backlog_queries import _resolve_write_db_path
            conn = connect(_resolve_write_db_path())
            try:
                rendered = build_body(conn, int(item_id)) or ""
            finally:
                conn.close()
            mode: SyncMode = "compact" if body_exceeds_budget(rendered) else "full"
        except Exception:  # pragma: no cover - mode is advisory metadata
            mode = "full"
        return True, mode
    except Exception as exc:
        print(f"Warning: sync_body failed for {item_ref_for_id(item_id)}: {exc}", file=out)
        return False, None


def _record_sync_failure(item_id: int, operation: str, reason: str = "unknown") -> None:
    """Emit a SyncFailed event."""
    _emit_event(
        "SyncFailed",
        item_id,
        {"operation": operation, "reason": reason, "item_id": item_id},
    )


def _render_body(item_id: int, out: TextIO = sys.stderr) -> bool:
    """No-op stub — body cache retired by. Returns True for compat."""
    return True


# ---------------------------------------------------------------------------
# GitHub repo resolution
# ---------------------------------------------------------------------------

def _resolve_project_github_repo(conn, project: str) -> str:
    """Read the verified GitHub App binding repo for migration comparison."""
    from yoke_core.domain import db_backend
    from yoke_core.domain.project_identity import resolve_project_id

    p = "%s" if db_backend.connection_is_postgres(conn) else "?"
    try:
        project_id = resolve_project_id(conn, project)
    except LookupError:
        return ""
    row = conn.execute(
        "SELECT COALESCE(github_repo, '') "
        f"FROM project_github_repo_bindings WHERE project_id = {p}",
        (project_id,),
    ).fetchone()
    if row and row[0]:
        return str(row[0])
    return ""
