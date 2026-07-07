"""Repair helpers for resync apply (PAT REST direct).

This module no longer threads a ``run_gh_fn`` callable through its
function signatures. Title edits and epic-task state changes call
``yoke_core.domain.github_rest`` directly; backlog YOK-* drift
branches still route through the ``backlog_github_sync`` siblings via
``call_domain_sync_fn`` — those siblings get migrated to the typed
surface in a later caller rewrite.
"""

from __future__ import annotations

import io
import os
import re
import sys
from typing import List, Optional, Tuple

from yoke_core.domain import (  # noqa: F401 - re-exported for tests
    backlog_github_sync,
    db_backend,
    epic_task_sync,
    github_rest,
)
from yoke_core.domain.db_helpers import connect  # noqa: F401 - re-exported for legacy callers
from yoke_core.domain.epic import task_update_field  # noqa: F401 - re-exported for legacy callers
from yoke_core.domain.project_github_auth import resolve_project_github_auth
from yoke_core.engines.resync_detect import DriftRecord, PairedItem


# sync_item announces title-match reuse with one of these markers.
_REUSE_MARKER_RE = re.compile(
    r"Found existing GitHub issue #(\d+) for YOK-\d+ — reusing"
    r"|Synced: YOK-\d+ → GitHub issue #(\d+) \(reused\)"
)


def _parent():
    from yoke_core.engines import resync as _resync
    return _resync


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _repair_local_orphan_backlog(
    item_id: str,
    project: str,
    call_domain_sync_fn,  # noqa: ARG001 - retained for wrapper compatibility
) -> Tuple[bool, bool, Optional[str]]:
    """Create or reuse a GitHub issue; returns ``(success, reused, issue_num)``.

    The engine switches the FIXED log wording between "created" and "reused
    existing" using ``reused``. :class:`ProjectGithubAuthError`
    propagates to the engine boundary.
    """
    num = item_id.replace("YOK-", "")
    auth = resolve_project_github_auth(project or "yoke")
    prior = os.environ.get("GH_TOKEN")
    os.environ["GH_TOKEN"] = auth.token
    captured = io.StringIO()
    try:
        rc = _parent().backlog_github_sync.sync_item(
            num, stdout=captured, stderr=io.StringIO(),
        )
    except Exception:
        return (False, False, None)
    finally:
        if prior is None:
            os.environ.pop("GH_TOKEN", None)
        else:
            os.environ["GH_TOKEN"] = prior
    if rc != 0:
        return (False, False, None)
    match = _REUSE_MARKER_RE.search(captured.getvalue())
    if match:
        return (True, True, match.group(1) or match.group(2))
    return (True, False, None)


def _repair_local_orphan_epic_task(
    item_id: str,
    project: str,
    db_path: str,
    is_dry_run_fn,
    task_update_field_fn=None,
) -> bool:
    """Create a GitHub issue for a local orphan epic task (typed REST).

    The implementation lives in
    :mod:`yoke_core.engines.resync_repair_epic_task_issue` so the body
    routes through the shared compact-mirror budget guard.
    """
    from yoke_core.engines.resync_repair_epic_task_issue import (
        repair_local_orphan_epic_task,
    )

    update_field = (
        task_update_field_fn
        if task_update_field_fn is not None
        else _parent().task_update_field
    )
    return repair_local_orphan_epic_task(
        item_id,
        project,
        db_path,
        is_dry_run_fn=is_dry_run_fn,
        task_update_field_fn=update_field,
    )


def _edit_issue_title_via_rest(
    *, project: str, number: int, title: str,
) -> bool:
    """Update the GitHub issue title via typed REST.

    Surfaces the typed failure reason to stderr so the operator log line
    names the actual cause (rate-limit, permission denied, transient
    transport) rather than collapsing into "title repair failed."
    """
    try:
        github_rest.update_issue(
            project=project or "yoke", number=int(number), title=title,
        )
    except github_rest.RateLimitedError as exc:
        print(f"  reason: rate-limited on title edit: {exc}", file=sys.stderr)
        return False
    except github_rest.RestAuthError as exc:
        print(f"  reason: permission denied on title edit: {exc}", file=sys.stderr)
        return False
    except github_rest.RestUnprocessableError as exc:
        print(f"  reason: GitHub rejected the title patch: {exc}", file=sys.stderr)
        return False
    except github_rest.RestTransportError as exc:
        print(f"  reason: transport failure on title edit: {exc}", file=sys.stderr)
        return False
    return True


def _set_issue_state_via_rest(
    *, project: str, number: int, state: str,
) -> bool:
    """Open or close the GitHub issue via typed REST."""
    try:
        github_rest.set_issue_state(
            project=project or "yoke", number=int(number), state=state,
        )
    except github_rest.RateLimitedError as exc:
        print(f"  reason: rate-limited on issue {state}: {exc}", file=sys.stderr)
        return False
    except github_rest.RestAuthError as exc:
        print(f"  reason: permission denied on issue {state}: {exc}", file=sys.stderr)
        return False
    except github_rest.RestTransportError as exc:
        print(f"  reason: transport failure on issue {state}: {exc}", file=sys.stderr)
        return False
    return True


def _repair_drift(
    drift: DriftRecord,
    paired: List[PairedItem],
    db_path: str,
    call_domain_sync_fn,
    is_dry_run_fn,
    query_item_status_fn,
) -> bool:
    """Repair a single field drift. Returns True on success."""
    paired_item = None
    for p in paired:
        if p.id == drift.id:
            paired_item = p
            break

    if drift.field == "title" and paired_item:
        if drift.id.startswith("YOK-"):
            repair_title = f"[{drift.id}] {drift.local}"
        else:
            et_slug = drift.id.split("/")[0]
            et_tnum_padded = drift.id.split("task-")[1] if "task-" in drift.id else ""
            from yoke_core.domain.db_helpers import connect

            conn = connect(db_path)
            p = _p(conn)
            parent = conn.execute(
                f"SELECT id FROM items WHERE CAST(id AS TEXT) = CAST({p} AS TEXT) LIMIT 1",
                (et_slug,),
            ).fetchone()
            conn.close()
            if parent:
                repair_title = f"[YOK-{parent[0]}] {et_tnum_padded} {drift.local}"
            else:
                repair_title = f"{et_tnum_padded} {drift.local}"

        if is_dry_run_fn():
            print(f"[DRY-RUN] Skipping GitHub: edit title for {drift.id}")
            return True

        return _edit_issue_title_via_rest(
            project=paired_item.project or "yoke",
            number=int(paired_item.gh_num),
            title=repair_title,
        )

    elif drift.field == "body":
        if drift.id.startswith("YOK-"):
            num = drift.id.replace("YOK-", "")
            return call_domain_sync_fn(
                _parent().backlog_github_sync.sync_body,
                num,
                project=paired_item.project if paired_item else "yoke",
            )
        elif "/task-" in drift.id:
            et_slug = drift.id.split("/")[0]
            et_tnum = drift.id.split("task-")[1].lstrip("0") or "0"
            return (
                _parent().epic_task_sync.sync_task_body(
                    str(et_slug),
                    int(et_tnum),
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )
                == 0
            )
        return False

    elif drift.field in (
        "label-status", "label-priority", "label-type",
        "label-source", "label-owner",
    ):
        if drift.id.startswith("YOK-"):
            num = drift.id.replace("YOK-", "")
            return call_domain_sync_fn(
                _parent().backlog_github_sync.sync_labels,
                num,
                project=paired_item.project if paired_item else "yoke",
            )
        return False

    elif drift.field in ("label-frozen", "label-blocked"):
        if drift.id.startswith("YOK-"):
            num = drift.id.replace("YOK-", "")
            kind = "frozen" if drift.field == "label-frozen" else "blocked"
            local_value = drift.local.replace(f"{kind}:", "")
            if is_dry_run_fn():
                print(f"[DRY-RUN] Skipping GitHub: sync-{kind}-label for YOK-{num}")
                return True
            sync_fn = (
                _parent().backlog_github_sync.sync_frozen_label
                if kind == "frozen"
                else _parent().backlog_github_sync.sync_blocked_label
            )
            return call_domain_sync_fn(
                sync_fn,
                num,
                local_value,
                project=paired_item.project if paired_item else "yoke",
            )
        return False

    elif drift.field == "state":
        if drift.id.startswith("YOK-"):
            num = drift.id.replace("YOK-", "")
            if drift.local == "CLOSED":
                return call_domain_sync_fn(
                    _parent().backlog_github_sync.close_issue,
                    num,
                    project=paired_item.project if paired_item else "yoke",
                )
            return call_domain_sync_fn(
                _parent().backlog_github_sync.reopen_issue,
                num,
                project=paired_item.project if paired_item else "yoke",
            )
        elif paired_item:
            if is_dry_run_fn():
                print(f"[DRY-RUN] Skipping GitHub: state change for {drift.id}")
                return True
            new_state = "closed" if drift.local == "CLOSED" else "open"
            return _set_issue_state_via_rest(
                project=paired_item.project or "yoke",
                number=int(paired_item.gh_num),
                state=new_state,
            )
        return False

    elif drift.field == "comment":
        if drift.id.startswith("YOK-"):
            num = drift.id.replace("YOK-", "")
            cur_status = query_item_status_fn(num) or "done"
            return call_domain_sync_fn(
                _parent().backlog_github_sync.post_comment,
                num,
                "unknown",
                cur_status,
                project=paired_item.project if paired_item else "yoke",
            )
        return False

    return False
