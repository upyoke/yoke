"""Backlog GitHub repo migration — `migrate_issue_to_repo` moves a
backlog item's GitHub issue from one repo to another, copying title,
body, labels, state, and comments, then forwarding and deleting the old
issue. Used by HC-wrong-repo-issues and project-change sync.

Yoke does NOT use the ``gh`` CLI; every GitHub interaction here goes
through the typed :mod:`yoke_core.domain.github_rest` surface.
"""

from __future__ import annotations

import sys
from typing import Any, Optional, TextIO

from yoke_core.domain.backlog_github_sync_accessor import bgs as _bgs
from yoke_core.domain import db_backend
from yoke_core.domain import github_rest
from yoke_core.domain.backlog_github_fetch import _close_if_owned, _open_conn, _p
from yoke_core.domain.project_github_auth import resolve_project_github_auth


def _list_issue_comments(*, project: str, number: int) -> list[dict]:
    """Fetch raw comment dicts for ``number`` in chronological order."""
    try:
        comments = github_rest.list_comments(project=project, number=number)
    except github_rest.RestTransportError:
        return []
    return [
        {
            "id": c.id,
            "body": c.body,
            "author": {"login": c.user_login},
            # GitHub list_comments returns chronological by default; the
            # typed wrapper preserves source order.
        }
        for c in comments
    ]


def migrate_issue_to_repo(
    item_id: str,
    old_issue_num: str,
    source_repo: str,
    target_repo: str,
    target_project: str,
    *,
    conn: Optional[Any] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    """Move a GitHub issue from one repo to another.

    Copies the full issue (title, body, labels, state, comments) to the
    target repo, updates the DB ``github_issue`` field, and deletes the
    old issue. Returns 0 on success, 1 on failure.

    Shared by HC-wrong-repo-issues and project-change sync.
    """
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    if _bgs()._dry_run():
        print(
            f"[DRY-RUN] Skipping GitHub: migrate-issue YOK-{item_id} "
            f"#{old_issue_num} {source_repo} → {target_repo}",
            file=stdout,
        )
        return 0
    # Migration is an explicit operator request that would CREATE an issue
    # in the target repo — refuse (not skip) when the target project is
    # backlog-only.
    if _bgs()._github_sync_skip(
        target_project, "migrate-issue", conn=conn, out=stderr,
    ):
        return 1
    if not _bgs()._github_auth_available(target_project):
        print(
            f"Error: project '{target_project}' has no usable GitHub App auth "
            "for migrate-issue",
            file=stderr,
        )
        return 1

    print(
        f"[migrate] YOK-{item_id}: migrating issue #{old_issue_num} "
        f"from {source_repo} to {target_repo}",
        file=stdout,
    )

    old_number = int(old_issue_num)

    # 1. Fetch the full source issue (title + body + labels + state).
    try:
        source_issue = github_rest.get_issue(project="yoke", number=old_number)
    except github_rest.RestTransportError as exc:
        print(
            f"[migrate] ERROR: could not fetch issue "
            f"#{old_issue_num} from {source_repo}: {exc}",
            file=stderr,
        )
        return 1
    if source_issue is None:
        print(
            f"[migrate] ERROR: issue #{old_issue_num} not found in {source_repo}",
            file=stderr,
        )
        return 1

    title = source_issue.title
    body = source_issue.body or ""
    labels = list(source_issue.labels)
    state = source_issue.state or ""

    # 2. Create new issue in target repo.
    try:
        created = github_rest.create_issue(
            project=target_project, title=title, body=body, labels=labels,
        )
    except github_rest.RestTransportError as exc:
        print(
            f"[migrate] ERROR: failed to create issue in {target_repo}: {exc}",
            file=stderr,
        )
        return 1
    new_issue_num = created.number
    if not new_issue_num:
        print(
            f"[migrate] ERROR: created issue carried no number ({created!r})",
            file=stderr,
        )
        return 1
    print(f"[migrate] Created #{new_issue_num} in {target_repo}", file=stdout)

    # 3. Copy comments in chronological order.
    comments = _list_issue_comments(project="yoke", number=old_number)
    for comment in comments:
        author = (comment.get("author") or {}).get("login", "unknown")
        body_text = comment.get("body", "")
        if not body_text:
            continue
        comment_text = (
            f"> *Migrated comment from @{author}:*\n\n{body_text}"
        )
        try:
            github_rest.post_comment(
                project=target_project, number=new_issue_num, body=comment_text,
            )
        except github_rest.RestTransportError as exc:
            print(
                f"[migrate] WARNING: failed to copy a comment: {exc}",
                file=stderr,
            )

    if comments:
        print(f"[migrate] Copied {len(comments)} comment(s)", file=stdout)

    # 4. Match state — close the new issue if old was closed.
    if state == "CLOSED":
        try:
            github_rest.set_issue_state(
                project=target_project, number=new_issue_num, state="closed",
            )
            print(
                f"[migrate] Closed #{new_issue_num} (matching source state)",
                file=stdout,
            )
        except github_rest.RestTransportError as exc:
            print(
                f"[migrate] WARNING: failed to close #{new_issue_num}: {exc}",
                file=stderr,
            )

    # 5. Update DB github_issue field.
    owns_conn = False
    db_conn: Optional[Any] = None
    try:
        db_conn, owns_conn = _open_conn(conn)
        p = _p(db_conn)
        db_conn.execute(
            f"UPDATE items SET github_issue = {p} WHERE id = {p}",
            (f"#{new_issue_num}", str(item_id)),
        )
        db_conn.commit()
    except (FileNotFoundError,) + db_backend.database_error_types(db_conn) as exc:
        print(f"[migrate] WARNING: DB update failed: {exc}", file=stderr)
    finally:
        _close_if_owned(db_conn if owns_conn else None, owns_conn)

    print(
        f"[migrate] Updated DB: YOK-{item_id} github_issue = #{new_issue_num}",
        file=stdout,
    )

    # 6. Close old issue with forwarding comment, then delete.
    forward_msg = (
        f"Migrated to {target_repo}#{new_issue_num} "
        f"(YOK-{item_id} project changed to {target_project})."
    )
    try:
        github_rest.post_comment(
            project="yoke", number=old_number, body=forward_msg,
        )
    except github_rest.RestTransportError as exc:
        print(
            f"[migrate] WARNING: failed to post forwarding comment: {exc}",
            file=stderr,
        )

    try:
        github_rest.set_issue_state(
            project="yoke", number=old_number, state="closed",
        )
    except github_rest.RestTransportError as exc:
        print(f"[migrate] WARNING: failed to close source: {exc}", file=stderr)

    try:
        github_rest.delete_issue(project="yoke", number=old_number)
        print(
            f"[migrate] Deleted #{old_issue_num} from {source_repo}",
            file=stdout,
        )
    except github_rest.RestTransportError as exc:
        print(
            f"[migrate] WARNING: failed to delete source issue: {exc}",
            file=stderr,
        )

    # 7. Emit structured event.
    try:
        from yoke_core.domain.events import emit_event
        emit_event(
            "IssueMigrated",
            event_kind="system",
            event_type="github_sync",
            source_type="script",
            severity="INFO",
            outcome="completed",
            item_id=str(item_id),
            project=target_project,
            context={
                "source_repo": source_repo,
                "target_repo": target_repo,
                "old_issue": int(old_issue_num),
                "new_issue": int(new_issue_num),
            },
            conn=conn,
        )
    except Exception:
        pass  # event emission is best-effort

    print(
        f"[migrate] YOK-{item_id}: migration complete "
        f"(#{old_issue_num} → #{new_issue_num})",
        file=stdout,
    )
    return 0


__all__ = ["migrate_issue_to_repo"]
