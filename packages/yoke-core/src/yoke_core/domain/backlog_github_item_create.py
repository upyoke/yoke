"""Backlog GitHub item create — `sync_item` creates or updates the GitHub
issue mirroring a backlog item. Handles dedup, label seeding, body upload,
and epic-child sync dispatch.

Companion `_regenerate_md` is a best-effort bridge to the backlog rendering
domain; kept in this module because it is only invoked from `sync_item`.

``sync_item`` invokes the canonical
:func:`yoke_core.domain.project_github_auth.resolve_project_github_auth`
**first** — before any dedup search, label seeding, body render, body-size
measurement, temp-file write, or ``gh`` subprocess launch. Both the
"already synced" branch (delegates to ``backlog_github_body_title_sync``)
and the "create new" branch route their body file through
:func:`backlog_github_body_budget.select_and_write_body_file` so the
body-budget contract holds across reuse and create paths.
"""

from __future__ import annotations

import sys
from typing import Any, Optional, TextIO

from yoke_core.domain.backlog_github_sync_accessor import bgs as _bgs
from yoke_core.domain import backlog_github_body_budget as _budget
from yoke_core.domain import github_rest
from yoke_core.domain.actors import actor_label_or_passthrough
from yoke_core.domain.backlog_github_fetch import (
    _close_if_owned,
    _item_context,
    _item_fields,
    _item_ref,
    _label_colors,
    _open_conn,
    _p,
    _resolve_item_id,
    _status_display_label,
)
from yoke_core.domain.backlog_github_label_sync import _ensure_label
from yoke_core.domain import project_label_policy
from yoke_core.domain.github_constraints import clamp_label_name
from yoke_core.domain.github_dedup import search_existing_issue
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    resolve_project_github_auth,
)


def sync_item(
    item_id: str,
    *,
    conn: Optional[Any] = None,
    stdout: Optional[TextIO] = None,
    stderr: Optional[TextIO] = None,
) -> int:
    """Create or update a GitHub issue for a backlog item.

    If not yet synced: creates the GitHub issue with labels.
    If already synced: updates labels and body.
    Epic items also sync child task issues + dispatch chains via the
    epic-task sync owner.
    """
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr

    owns_conn = False
    try:
        conn, owns_conn = _open_conn(conn)
    except FileNotFoundError:
        print("Error: DB not found", file=stderr)
        return 1

    try:
        try:
            item_pk = _resolve_item_id(item_id, conn=conn)
        except ValueError:
            print(f"Error: Item {item_id} not found in database", file=stderr)
            return 1
        item_ref = _item_ref(item_pk, conn=conn)

        # Read all needed fields upfront
        fields = _item_fields(
            item_pk,
            ["id", "title", "type", "priority", "status", "source", "owner", "github_issue", "worktree"],
            conn=conn,
        )
        if fields is None or not fields.get("id"):
            print(f"Error: Item {item_ref} not found in database", file=stderr)
            return 1

        item_type = fields["type"]
        gh_issue = fields["github_issue"]

        # Resolve repo and project upfront so the auth-first check (below)
        # has the right project label, and so the already-synced branch
        # also short-circuits cleanly on auth failure.
        context = _item_context(item_pk, conn=conn)
        if context is None:
            print(f"Error: Item {item_ref} not found", file=stderr)
            return 1
        _, project, repo = context
        gh_project = project or "yoke"

        # Backlog-only projects never mirror to GitHub: logged skip,
        # not an auth error. Gated before auth so a backlog-only project
        # without a GitHub App auth still short-circuits cleanly.
        if _bgs()._github_sync_skip(gh_project, "sync-item", conn=conn, out=stdout):
            return 0

        # Resolve project GitHub auth BEFORE any dedup search, label
        # seeding, body render, body-size measurement, temp-file write, or
        # gh subprocess launch.  On any typed auth failure the call returns
        # immediately and the body-budget check never runs.
        try:
            resolve_project_github_auth(gh_project, conn=conn)
        except ProjectGithubAuthError as exc:
            print(
                f"Error: sync_item short-circuit for {item_ref}: "
                f"{type(exc).__name__}: {exc}",
                file=stderr,
            )
            return 1

        if gh_issue and gh_issue != "null":
            # Already synced — update labels and body
            print(f"{item_ref} already synced to GitHub issue {gh_issue} — syncing labels and body", file=stdout)
            _bgs().sync_labels(item_pk, conn=conn, stdout=stdout, stderr=stderr)
            _bgs().sync_body(item_pk, conn=conn, stdout=stdout, stderr=stderr)
            return _bgs()._sync_epic_children(
                item_pk,
                item_type=item_type,
                conn=conn,
                stdout=stdout,
                stderr=stderr,
            )

        if _bgs()._dry_run():
            print(f"[DRY-RUN] Skipping GitHub: sync-item for {item_ref}", file=stdout)
            return 0
        if not _bgs()._github_auth_available(gh_project):
            print(
                f"Error: project '{gh_project}' has no usable GitHub App auth for sync",
                file=stderr,
            )
            return 1

        # Dedup: search for existing issue with exact public-ref title prefix.
        # GitHub's title search is fuzzy on bracketed/numeric tokens, so the
        # shared helper post-filters by exact-prefix match before reuse.
        search_prefix = f"[{item_ref}]"
        found = search_existing_issue(
            search_prefix,
            project=gh_project,
            stderr=stderr,
        )
        if found:
            reuse_num, _ = found
            print(f"Found existing GitHub issue #{reuse_num} for {item_ref} — reusing", file=stdout)
            p = _p(conn)
            conn.execute(
                f"UPDATE items SET github_issue = {p} WHERE id = {p}",
                (f"#{reuse_num}", item_pk),
            )
            conn.commit()
            _bgs()._regenerate_md(item_pk)
            print(f"Synced: {item_ref} → GitHub issue #{reuse_num} (reused)", file=stdout)
            return _bgs()._sync_epic_children(
                item_pk,
                item_type=item_type,
                conn=conn,
                stdout=stdout,
                stderr=stderr,
            )

        # Read field values for labels. Source and owner store actor
        # ids on current rows and legacy text labels on
        # pre-migration rows; the central helper bridges both shapes.
        title = fields["title"]
        priority = fields["priority"]
        status = fields["status"]
        source = fields["source"]
        owner = fields["owner"]
        worktree = fields["worktree"]
        # Render body on demand from structured fields.
        from yoke_core.domain.render_body import build_body
        body = build_body(conn, int(item_pk)) or ""

        colors = _label_colors()

        source_token = actor_label_or_passthrough(conn, source)
        owner_token = actor_label_or_passthrough(conn, owner)

        # Ensure labels exist
        status_label = f"status:{_status_display_label(status)}"
        type_label = f"type:{item_type}"
        pri_label = f"priority:{priority}"
        source_label = f"source:{source_token}" if source_token else ""
        owner_label = f"owner:{owner_token}" if owner_token else ""

        type_color = colors["type_epic"] if item_type == "epic" else colors["type_issue"]
        pri_color = project_label_policy.get_color(
            f"label_color_priority_{priority}", colors["status"],
        )

        _ensure_label(type_label, type_color, repo, gh_project)
        _ensure_label(pri_label, pri_color, repo, gh_project)
        _ensure_label(status_label, colors["status"], repo, gh_project)
        if source_label:
            _ensure_label(source_label, colors["source"], repo, gh_project)
        if owner_label:
            _ensure_label(owner_label, colors["owner"], repo, gh_project)

        # Build label list
        create_labels: list[str] = [type_label, pri_label, status_label]
        if source_label:
            create_labels.append(source_label)
        if owner_label:
            create_labels.append(owner_label)
        if worktree and worktree != "null":
            wt_label = clamp_label_name(f"worktree:{worktree.replace('/', '-')}")
            _ensure_label(wt_label, colors["worktree"], repo, gh_project, description=f"Worktree: {worktree}")
            create_labels.append(wt_label)

        # Select full body or compact mirror via the in-memory selector —
        # the typed REST surface accepts the body string directly, no
        # temp-file dance required.
        body_item_fields = {
            "title": title,
            "status": status,
            "type": item_type,
            "project": gh_project,
            "identity": item_ref,
        }
        selected_body, body_mode = _budget.select_body_for_github(
            body,
            item_fields=body_item_fields,
            conn=conn,
            item_id=int(item_pk),
        )

        print(f"Creating GitHub issue for {item_ref}: {title}", file=stdout)
        try:
            created = github_rest.create_issue(
                project=gh_project,
                title=f"[{item_ref}] {title}",
                body=selected_body,
                labels=create_labels,
            )
        except ProjectGithubAuthError as exc:
            print(
                f"Error: sync_item create transport short-circuit for "
                f"{item_ref}: {type(exc).__name__}: {exc}",
                file=stderr,
            )
            return 1
        except github_rest.RestTransportError as exc:
            print(f"Error: issue create failed: {exc}", file=stderr)
            return 1

        _budget.record_sync_mode(conn, int(item_pk), body_mode)
        _budget.emit_compact_notice(body_mode, int(item_pk), stderr)

        issue_num = created.number
        if not issue_num:
            print(f"Error: created issue has no number: {created!r}", file=stderr)
            return 1

        issue_url = created.html_url or f"https://github.com/{repo}/issues/{issue_num}" if repo else f"#{issue_num}"

        # Validate repo (created.html_url is authoritative when present)
        if repo and created.html_url:
            expected_fragment = f"/{repo.rstrip('/')}/"
            if expected_fragment not in created.html_url:
                print(
                    f"Warning: Issue #{issue_num} may have been created in the wrong repo",
                    file=stderr,
                )
                print(f"  Expected repo: {repo}", file=stderr)
                print(f"  Issue URL: {created.html_url}", file=stderr)

        # Update DB
        p = _p(conn)
        conn.execute(
            f"UPDATE items SET github_issue = {p} WHERE id = {p}",
            (f"#{issue_num}", item_pk),
        )
        conn.commit()
        _regenerate_md(item_pk)

        print(issue_url, file=stdout)
        print(f"Synced: {item_ref} → GitHub issue #{issue_num}", file=stdout)
        return _bgs()._sync_epic_children(
            item_pk,
            item_type=item_type,
            conn=conn,
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        _close_if_owned(conn, owns_conn)


def _regenerate_md(item_id: str) -> None:
    """Best-effort regeneration of backlog .md file."""
    try:
        item_id_int = int(str(item_id).lstrip("#"))
    except ValueError:
        return
    try:
        from yoke_core.domain import backlog as _backlog_domain
        _backlog_domain._generate_md(item_id_int, out=sys.stderr)
    except Exception:  # pragma: no cover - best-effort regeneration
        return


__all__ = ["sync_item", "_regenerate_md"]
