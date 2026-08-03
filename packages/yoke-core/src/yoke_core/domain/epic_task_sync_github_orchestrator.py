"""Create, link, and record GitHub issues for epic tasks."""

from __future__ import annotations

import sys
from typing import Any, Optional, TextIO

import yoke_core.domain.epic_task_sync_github as _etsg
import yoke_core.domain.epic_task_sync_github_orchestrator_body as _body
from yoke_core.domain import db_backend, github_rest
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.github_constraints import is_real_issue_num
from yoke_core.domain.item_worktrees import record_worker_item_worktree
from yoke_core.domain.worktree_naming import worktree_name_for_item
from yoke_core.domain.epic_task_sync import (
    _connect_db,
    _epic_parent_item_id,
    _epic_project,
    _epic_ref_name,
    _placeholder,
    _repo_root,
)
from yoke_core.domain.epic_task_sync_github_label_setup import (
    labels_for_task,
    prepare_required_labels,
)
from yoke_core.domain.epic_task_sync_github_orchestrator_setup import (
    finalize_sync,
    load_task_rows,
    preflight_sync,
)
from yoke_core.domain.project_github_auth import resolve_project_github_auth


def sync_epic_tasks(
    epic_ref: str,
    epic_dir: str = "",
    *,
    conn: Optional[Any] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    """Synchronize one epic's task issues."""
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    dry_run = _etsg._is_dry_run()

    if dry_run:
        print(
            "[DRY-RUN] Skipping GitHub: project auth/availability checks", file=stdout
        )

    owns_conn = conn is None
    if owns_conn:
        conn = _connect_db()

    try:
        p = _placeholder(conn)
        epic_name = _epic_ref_name(epic_ref, conn=conn, stderr=stderr)
        if epic_name is None:
            return 1

        project = _epic_project(epic_name, conn=conn)
        gh_project = project or "yoke"
        preflight_result = preflight_sync(
            conn,
            epic_name=epic_name,
            project=gh_project,
            dry_run=dry_run,
            stdout=stdout,
            stderr=stderr,
            resolver=resolve_project_github_auth,
        )
        if preflight_result is not None:
            return preflight_result

        try:
            repo_root = str(_repo_root())
        except (RuntimeError, FileNotFoundError):
            repo_root = ""  # no checkout: skip local worktree/dispatch scaffolding

        # Read parent backlog item info
        parent_item_id = _epic_parent_item_id(epic_name, conn=conn)
        backlog_id = f"YOK-{parent_item_id}" if parent_item_id else ""

        # Check for existing github_issue on backlog item
        backlog_github_issue = ""
        if parent_item_id:
            row = conn.execute(
                f"SELECT COALESCE(github_issue, '') FROM items WHERE id = {p}",
                (int(parent_item_id),),
            ).fetchone()
            gh_val = str(row[0] or "") if row else ""
            if gh_val and gh_val != "null":
                backlog_github_issue = gh_val.lstrip("#")

        status_color, worktree_color = prepare_required_labels(
            gh_project,
            dry_run=dry_run,
        )

        has_sub_issue = not dry_run

        task_rows = load_task_rows(conn, placeholder=p, epic_name=epic_name)

        epic_issue_num = _etsg._resolve_or_create_epic_issue(
            epic_name=epic_name,
            backlog_id=backlog_id,
            backlog_github_issue=backlog_github_issue,
            parent_item_id=parent_item_id,
            gh_project=gh_project,
            dry_run=dry_run,
            conn=conn,
            stdout=stdout,
            stderr=stderr,
        )
        if not dry_run and not is_real_issue_num(epic_issue_num):
            print("Error: epic parent issue create failed; aborting", file=stderr)
            return 1

        worktree_map: list[tuple[str, str]] = []  # (worktree_branch, task_num_str)
        task_list_lines: list[str] = []
        created = 0
        skipped = 0
        failed_tasks: list[str] = []

        for row in task_rows:
            (
                _db_id,
                _db_epic_id,
                db_tnum,
                db_title,
                db_wt,
                db_cest,
                db_deps,
                db_stat,
                _db_da,
            ) = row
            task_num_str = f"{int(db_tnum):03d}"

            # Idempotency: skip tasks that already have github_issue in DB
            existing_gh_row = conn.execute(
                f"SELECT github_issue FROM epic_tasks WHERE epic_id = {p} AND task_num = {p}",
                (epic_name, int(db_tnum)),
            ).fetchone()
            existing_gh = str(existing_gh_row[0] or "") if existing_gh_row else ""

            if existing_gh and existing_gh != "null" and is_real_issue_num(existing_gh):
                print(f"Skipping task {task_num_str} (already synced)", file=stdout)
                skipped += 1
                # Preserve an explicit worktree before falling back to the parent.
                skip_wt = db_wt
                if parent_item_id and not skip_wt:
                    skip_wt = f"YOK-{parent_item_id}"
                    print(
                        f"Warning: task {task_num_str} has empty worktree, "
                        f"defaulting to {skip_wt}",
                        file=stderr,
                    )
                    conn.execute(
                        f"UPDATE epic_tasks SET item_worktree_id = {p} WHERE epic_id = {p} AND task_num = {p}",
                        (
                            int(
                                record_worker_item_worktree(
                                    conn,
                                    item_id=int(epic_name),
                                    branch=skip_wt,
                                    path=None,
                                )["id"]
                            ),
                            epic_name,
                            int(db_tnum),
                        ),
                    )
                    conn.commit()
                if skip_wt:
                    worktree_map.append((skip_wt, task_num_str))
                continue

            # Legacy unslotted tasks fall back to the item's public ref.
            task_worktree = db_wt
            if parent_item_id and not task_worktree:
                task_worktree = worktree_name_for_item(conn, parent_item_id)
                print(
                    f"Warning: task {task_num_str} has empty worktree, "
                    f"defaulting to {task_worktree}",
                    file=stderr,
                )
                conn.execute(
                    f"UPDATE epic_tasks SET item_worktree_id = {p} WHERE epic_id = {p} AND task_num = {p}",
                    (
                        int(
                            record_worker_item_worktree(
                                conn,
                                item_id=int(epic_name),
                                branch=task_worktree,
                                path=None,
                            )["id"]
                        ),
                        epic_name,
                        int(db_tnum),
                    ),
                )
                conn.commit()

            task_title = db_title or f"Task {task_num_str}"

            task_status = str(db_stat or "").strip()
            if not task_status or task_status == "null":
                task_status = "planned"
            labels = labels_for_task(
                gh_project,
                task_status,
                task_worktree,
                status_color=status_color,
                worktree_color=worktree_color,
                dry_run=dry_run,
            )

            body_row = conn.execute(
                f"SELECT COALESCE(body, '') FROM epic_tasks WHERE epic_id = {p} AND task_num = {p}",
                (epic_name, int(db_tnum)),
            ).fetchone()
            task_body = str(body_row[0] or "") if body_row else ""

            # Build issue title
            if backlog_id:
                issue_title = f"[{backlog_id}] {task_num_str} {task_title}"
            else:
                issue_title = f"{task_num_str} {task_title}"

            # Create or dedup
            if dry_run:
                task_issue_num = "0"
                print(
                    f"[DRY-RUN] Skipping GitHub: would create task issue "
                    f"'{issue_title}' (using placeholder #0)",
                    file=stdout,
                )
            else:
                task_issue_num = _etsg._dedup_or_create_task_issue(
                    backlog_id=backlog_id,
                    task_num_str=task_num_str,
                    task_title=task_title,
                    issue_title=issue_title,
                    task_body=task_body,
                    labels=labels,
                    gh_project=gh_project,
                    stdout=stdout,
                    stderr=stderr,
                    conn=conn,
                    epic_id=str(parent_item_id) if parent_item_id else "",
                    task_num=int(db_tnum),
                )

            # A real-mode sentinel skips persistence so the next sync retries.
            if not dry_run and not is_real_issue_num(task_issue_num):
                print(
                    f"Warning: task {task_num_str} create failed; "
                    f"leaving github_issue NULL",
                    file=stderr,
                )
                failed_tasks.append(task_num_str)
                continue

            created += 1

            # Record worktree mapping
            if task_worktree:
                worktree_map.append((task_worktree, task_num_str))

            if dry_run:
                print("[DRY-RUN] Skipping GitHub: would link task to epic", file=stdout)
            elif has_sub_issue:
                try:
                    github_rest.add_sub_issue(
                        project=gh_project,
                        parent_number=int(epic_issue_num),
                        child_number=int(task_issue_num),
                    )
                except (github_rest.RestTransportError, ValueError):
                    has_sub_issue = False
                    task_list_lines.append(f"- [ ] #{task_issue_num} — {task_title}")
            else:
                task_list_lines.append(f"- [ ] #{task_issue_num} — {task_title}")

            # Write back to DB
            conn.execute(
                f"UPDATE epic_tasks SET github_issue = {p} WHERE epic_id = {p} AND task_num = {p}",
                (f"#{task_issue_num}", epic_name, int(db_tnum)),
            )
            if task_worktree and repo_root:
                wt_slug = task_worktree.replace("/", "-")
                wt_path = f"{repo_root}/.worktrees/{wt_slug}"
                lane = record_worker_item_worktree(
                    conn,
                    item_id=int(epic_name),
                    branch=task_worktree,
                    path=wt_path,
                )
                conn.execute(
                    f"UPDATE epic_tasks SET item_worktree_id = {p} WHERE epic_id = {p} AND task_num = {p}",
                    (int(lane["id"]), epic_name, int(db_tnum)),
                )
            conn.commit()

            # Insert history entry
            try:
                conn.execute(
                    f"""INSERT INTO epic_task_history (epic_id, task_num, from_status, to_status, note, created_at)
                       VALUES ({p}, {p}, {p}, {p}, {p}, {p})""",
                    (
                        epic_name,
                        int(db_tnum),
                        "none",
                        "pending",
                        "Created via sync",
                        iso8601_now(),
                    ),
                )
                conn.commit()
            except db_backend.operational_error_types(conn):
                conn.rollback()
                pass  # history table may not exist in test fixtures

        return finalize_sync(
            dry_run=dry_run,
            has_sub_issue=has_sub_issue,
            task_list_lines=task_list_lines,
            epic_issue_num=epic_issue_num,
            project=gh_project,
            parent_item_id=parent_item_id,
            conn=conn,
            stderr=stderr,
            repo_root=repo_root,
            epic_name=epic_name,
            worktree_map=worktree_map,
            stdout=stdout,
            created=created,
            skipped=skipped,
            failed_tasks=failed_tasks,
            body_writer=_body.append_task_list_to_epic_body,
        )
    finally:
        if owns_conn and conn is not None:
            conn.close()
