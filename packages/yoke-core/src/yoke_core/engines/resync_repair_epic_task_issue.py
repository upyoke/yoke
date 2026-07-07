"""Resync repair: local-orphan epic-task GitHub issue creation.

Routes through Yoke's typed REST surface
(:mod:`yoke_core.domain.github_rest`). The compact-mirror body-budget
gate (:mod:`yoke_core.domain.backlog_github_body_budget`) still picks
between the full body and the small breadcrumb so oversized task
bodies do not trip "GraphQL: Body is too long" on issue creation.

Returns a typed :class:`RepairOutcome` carrying ``success: bool`` plus
``error: str`` so the caller can surface the actual REST failure in
the FAILED log line (rate-limit, permission denied, transient transport,
unprocessable). Wrapper ``resync_repair._repair_local_orphan_epic_task``
keeps the boolean contract for the existing dispatch surface.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Optional, TextIO

from yoke_core.domain import backlog_github_body_budget as _budget
from yoke_core.domain import backlog_github_body_writer as _writer
from yoke_core.domain import db_backend
from yoke_core.domain import github_rest
from yoke_core.domain.db_helpers import connect
from yoke_core.domain.epic import task_get_body
from yoke_core.domain.lifecycle import TASK_TERMINAL_SUCCESS


@dataclass(frozen=True)
class RepairOutcome:
    """Typed outcome from a repair function (diagnostic shape)."""

    success: bool
    error: str = ""
    issue_number: int = 0


def _task_id_for_mirror(parent_item_id: Optional[str], task_num: int) -> int:
    """Pack the epic id and task_num into a stable mirror id (only used
    when the body exceeds budget)."""
    try:
        epic_int = int(parent_item_id) if parent_item_id else 0
    except (TypeError, ValueError):
        epic_int = 0
    return epic_int * 1000 + int(task_num)


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _select_body_for_create(
    body: str, *, project: str, title: str, status: str,
    et_slug: str, et_tnum: str, parent_id: str, stderr: TextIO,
) -> str:
    """Pick the issue body — full or compact mirror — and emit the
    compact-mirror notice when truncating."""
    selected, mode = _budget.select_body_for_github(
        body, item_fields={
            "title": title, "status": status, "type": "task",
            "project": project or "yoke",
            "identity": _writer.epic_task_identity(et_slug, et_tnum),
            "body_command": _writer.epic_task_body_command(et_slug, et_tnum),
            "next_actions": _writer.epic_task_next_actions(et_slug),
        },
        conn=None,
        item_id=_task_id_for_mirror(parent_id, int(et_tnum)),
    )
    _budget.emit_compact_notice(mode, int(et_tnum), stderr)
    return selected


def repair_local_orphan_epic_task(
    item_id: str,
    project: str,
    db_path: str,
    *,
    is_dry_run_fn,
    task_update_field_fn=None,
) -> bool:
    """Create a GitHub issue for a local-orphan epic task via typed REST.

    Returns a bool to keep the existing caller contract. The typed
    failure reason is printed to stderr so the FAILED log line surfaces
    the actual cause (rate-limit, permission denied, etc.) instead of
    "could not create GitHub issue."
    """
    outcome = repair_local_orphan_epic_task_typed(
        item_id, project, db_path,
        is_dry_run_fn=is_dry_run_fn,
        task_update_field_fn=task_update_field_fn,
        stderr=sys.stderr,
    )
    if not outcome.success and outcome.error:
        print(
            f"  reason: {outcome.error}",
            file=sys.stderr,
        )
    return outcome.success


def repair_local_orphan_epic_task_typed(
    item_id: str,
    project: str,
    db_path: str,
    *,
    is_dry_run_fn,
    task_update_field_fn=None,
    stderr: TextIO = sys.stderr,
) -> RepairOutcome:
    """Typed variant returning RepairOutcome — direct caller path for
    future-shape diagnostic-aware loops."""
    parts = item_id.split("/task-")
    if len(parts) != 2:
        return RepairOutcome(False, error=f"malformed task id: {item_id!r}")
    et_slug, et_tnum_padded = parts
    et_tnum = et_tnum_padded.lstrip("0") or "0"

    conn = connect(path=db_path)
    try:
        p = _p(conn)
        parent_row = conn.execute(
            f"SELECT id FROM items WHERE CAST(id AS TEXT) = CAST({p} AS TEXT) LIMIT 1",
            (et_slug,),
        ).fetchone()
        task_row = conn.execute(
            f"SELECT title, status FROM epic_tasks WHERE epic_id = {p} AND task_num = {p}",
            (et_slug, int(et_tnum)),
        ).fetchone()
    finally:
        conn.close()

    if not task_row:
        return RepairOutcome(False, error=f"epic_tasks row {et_slug}/{et_tnum} not found")

    et_title, et_status = task_row
    et_status = et_status or "planned"

    if is_dry_run_fn():
        return RepairOutcome(True)

    issue_title = (
        f"[YOK-{parent_row[0]}] {et_tnum_padded} {et_title}"
        if parent_row else f"{et_tnum_padded} {et_title}"
    )
    label_list = ["type:task", f"status:{et_status}"]

    raw_body = ""
    try:
        conn_db = connect(path=db_path)
        try:
            raw_body = task_get_body(conn_db, str(et_slug), int(et_tnum)) or ""
        finally:
            conn_db.close()
    except Exception:
        raw_body = ""

    selected_body = _select_body_for_create(
        raw_body, project=project, title=issue_title, status=et_status,
        et_slug=et_slug, et_tnum=et_tnum,
        parent_id=str(parent_row[0]) if parent_row else "",
        stderr=stderr,
    )

    try:
        issue = github_rest.create_issue(
            project=project or "yoke",
            title=issue_title, body=selected_body, labels=label_list,
        )
    except github_rest.RateLimitedError as exc:
        return RepairOutcome(False, error=f"rate-limited on issue create: {exc}")
    except github_rest.RestAuthError as exc:
        return RepairOutcome(False, error=f"permission denied on issue create: {exc}")
    except github_rest.RestUnprocessableError as exc:
        return RepairOutcome(False, error=f"GitHub rejected the create payload: {exc}")
    except github_rest.RestTransportError as exc:
        return RepairOutcome(False, error=f"transport failure on issue create: {exc}")
    except Exception as exc:  # noqa: BLE001 — surface unexpected errors in log line
        return RepairOutcome(False, error=f"unexpected error on issue create: {exc!r}")

    issue_num = issue.number
    if not issue_num:
        return RepairOutcome(False, error="create returned issue with no number")

    if task_update_field_fn is not None:
        try:
            conn_db = connect(path=db_path)
            try:
                task_update_field_fn(
                    conn_db, str(et_slug), int(et_tnum),
                    "github_issue", f"#{issue_num}",
                )
            finally:
                conn_db.close()
        except Exception:
            pass

    if et_status in TASK_TERMINAL_SUCCESS or et_status == "cancelled":
        try:
            github_rest.set_issue_state(
                project=project or "yoke", number=issue_num, state="closed",
            )
        except github_rest.RestTransportError:
            # Best-effort terminal-state close — the issue exists; a
            # follow-up resync sweep will re-pick this up if needed.
            pass

    return RepairOutcome(True, issue_number=issue_num)


__all__ = ["repair_local_orphan_epic_task", "repair_local_orphan_epic_task_typed", "RepairOutcome"]
