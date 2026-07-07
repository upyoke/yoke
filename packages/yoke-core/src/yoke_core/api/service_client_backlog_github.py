"""GitHub-relay command handler for the service_client backlog CLI surface.

Owns ``backlog-github`` — the relay entrypoint that maps subcommands to the
``backlog_github_sync`` domain helpers (sync-item, sync-labels, sync-body,
close-issue, post-comment).

Each item-scoped mutation runs the allow-unclaimed ownership guard
(``backlog_github_sync_cli.check_ownership``) before any GitHub call:
the mutation proceeds when no live work claim exists or when the calling
session holds it, and is denied only when another live session holds
the claim. Read-only modes and ``YOKE_DRY_RUN=1`` paths are exempt.
"""

from __future__ import annotations

import sys


_USAGE_LINE = (
    "Usage: backlog-github "
    "<sync-item|sync-labels|sync-body|close-issue|post-comment|"
    "backfill-oversized-bodies> ..."
)


def _guard(item_id_raw: str, mode_label: str) -> int:
    # Import inside the function so the relay does not pull
    # ``backlog_github_sync_cli`` (and its sibling re-export chain) at
    # module load — that would cycle through ``service_client`` because
    # the CLI siblings import shared helpers that themselves transitively
    # load the relay.
    from yoke_core.domain.backlog_github_sync_cli import check_ownership

    allow, _reason, holder = check_ownership(item_id_raw)
    if allow:
        return 0
    print(
        f"Refusing to {mode_label} for {item_id_raw}: "
        f"work claim held by session {holder}",
        file=sys.stderr,
    )
    return 1


def cmd_backlog_github(args: list[str]) -> int:
    """Relay backlog GitHub helper commands to the Python domain owner."""
    from yoke_core.domain import backlog
    from yoke_core.domain import backlog_github_sync
    from yoke_core.domain import backlog_github_sync_cli

    if not args:
        print(_USAGE_LINE, file=sys.stderr)
        return 2

    mode = args[0]
    rest = args[1:]
    if mode == "sync-item" and len(rest) == 1:
        rc = _guard(rest[0], "sync item")
        if rc:
            return rc
        rc = backlog_github_sync.sync_item(rest[0])
        if rc == 0:
            backlog._maybe_rebuild_board(True)
        return rc
    if mode == "sync-labels" and len(rest) == 1:
        rc = _guard(rest[0], "sync labels")
        if rc:
            return rc
        return backlog_github_sync.sync_labels(rest[0])
    if mode == "sync-body" and len(rest) == 1:
        rc = _guard(rest[0], "sync body")
        if rc:
            return rc
        return backlog_github_sync.sync_body(rest[0])
    if mode == "close-issue" and len(rest) == 1:
        rc = _guard(rest[0], "close issue")
        if rc:
            return rc
        return backlog_github_sync.close_issue(rest[0])
    if mode == "post-comment" and len(rest) == 3:
        rc = _guard(rest[0], "post comment")
        if rc:
            return rc
        return backlog_github_sync.post_comment(rest[0], rest[1], rest[2])
    if mode == "backfill-oversized-bodies" and not rest:
        return backlog_github_sync_cli.backfill_oversized_bodies()

    print(_USAGE_LINE, file=sys.stderr)
    return 2


__all__ = [
    "cmd_backlog_github",
]
