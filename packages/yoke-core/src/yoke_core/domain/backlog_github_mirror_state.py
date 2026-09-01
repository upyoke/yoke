"""What an item's GitHub mirror actually is after a create attempt.

Creating a work item and mirroring it to a GitHub issue are two writes, and
only the first is authoritative. The second used to fail into a
``Note: GitHub sync skipped (non-fatal)`` line: the create reported
success, ``github_issue`` stayed null, and nothing recorded that the mirror
the operator was promised does not exist. On a project with no GitHub App
bound that is the honest steady state and should be stamped as such; on a
bound project it is a failure, and the difference is exactly what the
operator needs to see.

The stamped state is derived from the authority — whether the item ended up
carrying a ``github_issue`` — rather than from the sync's own report, so a
sync that returns success without opening an issue is still counted as the
absence it is.
"""

from __future__ import annotations

import sys
from typing import Any, Optional, TextIO

#: What one mirror attempt reported.
MIRROR_ATTEMPT_SYNCED = "synced"
MIRROR_ATTEMPT_SKIPPED = "skipped"
MIRROR_ATTEMPT_FAILED = "failed"

#: What the item's mirror state actually is afterwards.
MIRROR_STATE_MIRRORED = "mirrored"
MIRROR_STATE_UNMIRRORED = "unmirrored"
MIRROR_STATE_FAILED = "failed"

UNMIRRORED_EVENT_NAME = "ItemMirrorAbsent"


def _github_issue(conn: Any, item_id: int) -> str:
    from yoke_core.domain import db_backend

    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    row = conn.execute(
        f"SELECT github_issue FROM items WHERE id = {marker}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return ""
    value = row["github_issue"] if hasattr(row, "keys") else row[0]
    return "" if value is None or str(value) == "null" else str(value)


def record_mirror_state(
    conn: Any,
    *,
    item_id: int,
    public_ref: str,
    project: str,
    attempt: str,
    out: Optional[TextIO] = None,
) -> str:
    """Stamp the item's mirror state and return it.

    A bound project that ends up without an issue surfaces the failure; an
    unbound one records the honest no-mirror state. Either way the absence
    is named on stdout and recorded as an event, so ``github_issue`` being
    null is a fact somebody wrote down rather than one nobody noticed.
    """
    out = out if out is not None else sys.stderr
    if _github_issue(conn, item_id):
        return MIRROR_STATE_MIRRORED

    from yoke_core.domain.backlog_rendering import (
        _record_sync_failure,
        _resolve_project_github_repo,
    )

    repo = _resolve_project_github_repo(conn, project)
    bound = bool(repo)
    state = (
        MIRROR_STATE_FAILED
        if bound and attempt != MIRROR_ATTEMPT_SKIPPED
        else MIRROR_STATE_UNMIRRORED
    )
    if state == MIRROR_STATE_FAILED:
        print(
            f"Warning: {public_ref} has no GitHub issue — project {project!r} "
            f"is bound to {repo} but the mirror attempt {attempt}. "
            f"Converge it with `yoke resync --fix`.",
            file=out,
        )
        _record_sync_failure(
            item_id, "create", f"create mirror attempt {attempt} for {public_ref}"
        )
    else:
        print(
            f"Note: {public_ref} is unmirrored (github_issue null) — "
            + (
                f"the mirror attempt was {attempt}."
                if bound
                else f"project {project!r} has no GitHub repository bound."
            ),
            file=out,
        )
    _emit_absence(item_id, project=project, state=state, attempt=attempt, bound=bound)
    return state


def sync_and_record_mirror(
    conn: Any,
    *,
    item_id: int,
    public_ref: str,
    project: str,
    out: Optional[TextIO] = None,
) -> str:
    """Mirror one freshly created item and stamp what the mirror became."""
    from yoke_core.domain import backlog_rendering

    out = out if out is not None else sys.stderr
    attempt = backlog_rendering._sync_item(item_id, out)
    return record_mirror_state(
        conn,
        item_id=item_id,
        public_ref=public_ref,
        project=project,
        attempt=attempt,
        out=out,
    )


def _emit_absence(
    item_id: int, *, project: str, state: str, attempt: str, bound: bool
) -> None:
    from yoke_core.domain.backlog_rendering import _emit_event

    _emit_event(
        UNMIRRORED_EVENT_NAME,
        item_id,
        {
            "project": project,
            "mirror_state": state,
            "attempt": attempt,
            "github_app_bound": bound,
        },
    )


__all__ = [
    "MIRROR_ATTEMPT_FAILED",
    "MIRROR_ATTEMPT_SKIPPED",
    "MIRROR_ATTEMPT_SYNCED",
    "MIRROR_STATE_FAILED",
    "MIRROR_STATE_MIRRORED",
    "MIRROR_STATE_UNMIRRORED",
    "UNMIRRORED_EVENT_NAME",
    "record_mirror_state",
    "sync_and_record_mirror",
]
