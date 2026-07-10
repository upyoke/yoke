"""Post-merge status and item side effects for done-transition (bearer-token REST).

GitHub batch sync (label add, status comment, close) for cascaded epic
tasks routes through the canonical bearer-token REST transport
(:mod:`yoke_core.domain.gh_rest_transport`). The legacy host-``gh``
path has been retired.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
)
from yoke_core.domain import db_backend
from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
    split_repo,
)
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    resolve_project_github_auth,
)


def _parent():
    from yoke_core.engines import done_transition as _dt
    return _dt


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _populate_merged_at(item_id: int) -> None:
    """Populate merged_at if not already set."""
    print("--- Populating merged_at (pre-flight) ---")
    existing = _parent()._query_item_field(item_id, "merged_at")
    if existing and existing != "null":
        print(f"  merged_at already set: {existing}")
        return
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with _parent()._connect() as conn:
        p = _p(conn)
        conn.execute(
            f"UPDATE items SET merged_at = {p} WHERE id = {p}",
            (now, item_id),
        )
    print(f"  merged_at set to {now}")


def _update_status_to_done(
    item_id: int, skip_qa: bool, max_retries: int = 3
) -> bool:
    """Update item status to done with retry logic.

    This engine owns the done transition, so it asserts
    ``done_nonce_verified=True`` directly to :func:`backlog.execute_update`.

    Returns True on success.
    """
    env_overrides = {
        "YOKE_CLAIM_BYPASS": f"done-transition:YOK-{item_id}",
        "YOKE_STATUS_SOURCE": "done-transition",
        "YOKE_QA_GATE_BYPASS": "1" if skip_qa else "0",
    }
    for attempt in range(1, max_retries + 1):
        exit_code = _parent()._update_item_direct(
            item_id,
            "status",
            "done",
            env_overrides=env_overrides,
            done_nonce_verified=True,
            qa_bypass=skip_qa,
            rebuild_board=False,
            no_github=True,
        )
        if exit_code == 0:
            return True
        # Verify status despite non-zero exit
        print(
            f"Warning: backlog update status exited nonzero "
            f"(attempt {attempt}/{max_retries})",
            file=sys.stderr,
        )
        verify = _parent()._query_item_field(item_id, "status")
        if verify == "done":
            print("Status verified: done (exit code was from a "
                  "non-critical side-effect)", file=sys.stderr)
            return True
        if attempt < max_retries:
            print(f"Status is still '{verify}' — retrying in 2 seconds... "
                  "", file=sys.stderr)
            import time
            time.sleep(2)
    print(f"Status update failed after {max_retries} attempts.",
          file=sys.stderr)
    return False


def _cascade_epic_tasks_to_done(item_id: int, epic_name: str) -> None:
    """Cascade done status to all non-done epic tasks."""
    from yoke_core.domain import epic as _epic_domain

    print("=== Step 6b: Epic sub-task cascade ===")
    with _parent()._connect() as conn:
        task_list_output = _epic_domain.task_list(conn, epic_name)
    if not task_list_output or not task_list_output.strip():
        print("No tasks to cascade.")
        return

    cascade_count = 0
    promoted_count = 0
    task_nums: list[str] = []

    for line in task_list_output.strip().split("\n"):
        if not line.strip():
            continue
        parts = line.split("|")
        if len(parts) < 8:
            continue
        task_num = parts[2].strip()
        task_status = parts[7].strip()
        if task_status == "done":
            continue

        env_overrides = {
            "YOKE_TASK_DONE_VERIFIED": "1",
            "YOKE_CLAIM_BYPASS": f"done-cascade:YOK-{item_id}",
        }
        if task_status == "reviewed-implementation":
            _parent()._update_task_status_direct(
                epic_name,
                task_num,
                "done",
                f"Auto-promoted: task in done epic YOK-{item_id}",
                env_overrides=env_overrides,
            )
            print(f"  Promoted: task {task_num} (reviewed-implementation -> done)")
            promoted_count += 1
        else:
            _parent()._update_task_status_direct(
                epic_name,
                task_num,
                "done",
                f"Auto-done: epic YOK-{item_id} marked done",
                env_overrides=env_overrides,
            )
            print(f"  Cascaded: task {task_num} ({task_status} -> done)")
            cascade_count += 1
        task_nums.append(task_num)

    print(f"Sub-task cascade complete: {cascade_count} cascaded, "
          f"{promoted_count} promoted.")

    # Batch GitHub sync
    if task_nums:
        _batch_github_sync_tasks(item_id, epic_name, task_nums)


def _batch_github_sync_tasks(
    item_id: int, epic_name: str, task_nums: list[str]
) -> None:
    """Post batch GitHub summary for cascaded tasks via bearer-token REST."""
    item_project = _parent()._query_item_field(item_id, "project") or "yoke"

    try:
        auth = resolve_project_github_auth(
            item_project,
            required_permissions=GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
        )
    except ProjectGithubAuthError as exc:
        print(
            f"Warning: skipping batch GitHub sync for {len(task_nums)} task(s); "
            f"project '{item_project}' auth not configured ({exc.code})",
            file=sys.stderr,
        )
        return

    try:
        owner, repo = split_repo(auth.repo)
    except ValueError:
        print(
            f"Warning: project '{item_project}' has malformed github_repo "
            f"'{auth.repo}'; skipping batch sync",
            file=sys.stderr,
        )
        return

    from yoke_core.domain.project_label_policy import get_color

    color = get_color("label_color_status", "C5DEF5")

    # Ensure the status:done label exists (idempotent).
    try:
        request_with_retry(
            RestRequest(
                method="POST",
                path=f"/repos/{owner}/{repo}/labels",
                body={
                    "name": "status:done",
                    "color": color,
                    "description": "Yoke status label",
                },
            ),
            token=auth.token,
        )
    except RestTransportError:
        pass  # 422 already-exists is fine

    print("\n--- Batch GitHub sync for cascaded tasks ---")
    for tnum in task_nums:
        with _parent()._connect() as conn:
            row = conn.execute(
                "SELECT COALESCE(github_issue, '') FROM epic_tasks "
                f"WHERE epic_id = {_p(conn)} AND task_num = {_p(conn)}",
                (epic_name, tnum),
            ).fetchone()
        if not row or not row[0]:
            continue
        gh_inum = str(row[0]).replace("#", "")
        if not gh_inum:
            continue
        # Add label
        try:
            request_with_retry(
                RestRequest(
                    method="POST",
                    path=f"/repos/{owner}/{repo}/issues/{gh_inum}/labels",
                    body={"labels": ["status:done"]},
                ),
                token=auth.token,
            )
        except RestTransportError:
            pass
        # Post comment
        body_text = f"**Status:** -> done (epic YOK-{item_id} cascade)"
        try:
            request_with_retry(
                RestRequest(
                    method="POST",
                    path=f"/repos/{owner}/{repo}/issues/{gh_inum}/comments",
                    body={"body": body_text},
                ),
                token=auth.token,
            )
        except RestTransportError:
            pass
        # Close
        try:
            request_with_retry(
                RestRequest(
                    method="PATCH",
                    path=f"/repos/{owner}/{repo}/issues/{gh_inum}",
                    body={"state": "closed"},
                ),
                token=auth.token,
            )
        except RestTransportError:
            pass
        print(f"  GitHub: #{gh_inum} labeled+commented+closed")
    print("Batch GitHub sync complete.")
