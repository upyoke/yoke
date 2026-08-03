"""Repair helpers for resync apply (bearer-token REST direct).

This module no longer threads a ``run_gh_fn`` callable through its
function signatures. Title edits and epic-task state changes call
``yoke_core.domain.github_rest`` directly; backlog YOK-* drift
branches still route through the ``backlog_github_sync`` siblings via
``call_domain_sync_fn`` — those siblings get migrated to the typed
surface in a later caller rewrite.
"""

from __future__ import annotations

import io
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
from yoke_core.domain.project_github_auth import resolve_project_github_auth
from yoke_core.engines.resync_detect import DriftRecord, PairedItem


# sync_item announces title-match reuse with one of these markers; the
# public-ref prefix letters vary per project.
_REUSE_MARKER_RE = re.compile(
    r"Found existing GitHub issue #(\d+) for [A-Za-z][A-Za-z0-9]*-\d+ — reusing"
    r"|Synced: [A-Za-z][A-Za-z0-9]*-\d+ → GitHub issue #(\d+) \(reused\)"
)


def _parent():
    from yoke_core.engines import resync as _resync
    return _resync


def _p(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _lookup_item_ref_over_transport(ref: str) -> str:
    """Resolve an item's public ref by internal-id reference over the transport.

    Relays ``resync.item_lookup`` so the epic-parent lookup that builds the
    ``[<public-ref>]`` title prefix runs over an https control plane as well
    as a local Postgres connection. The public ref is rendered server-side
    from the project's prefix and the item's project sequence, so no caller
    ever reconstructs it from an internal id. A read failure raises,
    matching the inline ``connect()`` the engine never guarded; a missing
    item yields ``""`` (the engine falls back to an unprefixed title).
    """
    from yoke_contracts.api.function_call import TargetRef
    from yoke_core.api.service_client_structured_api_adapter import call_dispatcher

    resp = call_dispatcher(
        function_id="resync.item_lookup",
        target=TargetRef(kind="global"),
        payload={"ref": str(ref)},
    )
    if not resp.success:
        message = resp.error.message if resp.error else "unknown error"
        raise RuntimeError(f"resync parent-ref lookup failed: {message}")
    data = resp.result or {}
    if not data.get("found"):
        return ""
    return str(data.get("ref") or "")


def _repair_local_orphan_backlog(
    item_id: int,
    project: str,
    call_domain_sync_fn,  # noqa: ARG001 - retained for wrapper compatibility
) -> Tuple[bool, bool, Optional[str]]:
    """Create or reuse a GitHub issue; returns ``(success, reused, issue_num)``.

    ``item_id`` is the internal ``items.id``; the digit-string form is a
    bare internal-id token to the domain sync surface. The engine
    switches the FIXED log wording between "created" and "reused
    existing" using ``reused``. :class:`ProjectGithubAuthError`
    propagates to the engine boundary.
    """
    resolve_project_github_auth(project or "yoke")
    captured = io.StringIO()
    try:
        rc = _parent().backlog_github_sync.sync_item(
            str(int(item_id)), stdout=captured, stderr=io.StringIO(),
        )
    except Exception:
        return (False, False, None)
    if rc != 0:
        return (False, False, None)
    match = _REUSE_MARKER_RE.search(captured.getvalue())
    if match:
        return (True, True, match.group(1) or match.group(2))
    return (True, False, None)


def _repair_local_orphan_epic_task(
    epic_id: str,
    task_num: int,
    project: str,
    db_path: str,
    is_dry_run_fn,
) -> bool:
    """Create a GitHub issue for a local orphan epic task (typed REST).

    The implementation lives in
    :mod:`yoke_core.engines.resync_repair_epic_task_issue` so the body
    routes through the shared compact-mirror budget guard; the
    ``github_issue`` write-back relays through the connected transport.
    """
    from yoke_core.engines.resync_repair_epic_task_issue import (
        repair_local_orphan_epic_task,
    )

    return repair_local_orphan_epic_task(
        epic_id,
        task_num,
        project,
        db_path,
        is_dry_run_fn=is_dry_run_fn,
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


def _find_paired_for_drift(
    drift: DriftRecord, paired: List[PairedItem],
) -> Optional[PairedItem]:
    """Match a drift back to its paired item by typed identity."""
    for p in paired:
        if drift.item_id is not None and p.item_id == drift.item_id:
            return p
        if (
            drift.epic_id is not None
            and p.epic_id == drift.epic_id
            and p.task_num == drift.task_num
        ):
            return p
    return None


def _epic_task_repair_title(drift: DriftRecord) -> str:
    """Compose the epic-task issue title with the parent's public ref."""
    tnum_padded = f"{int(drift.task_num):03d}"
    parent_ref = _lookup_item_ref_over_transport(str(drift.epic_id))
    if parent_ref:
        return f"[{parent_ref}] {tnum_padded} {drift.local}"
    return f"{tnum_padded} {drift.local}"


def _repair_drift(
    drift: DriftRecord,
    paired: List[PairedItem],
    db_path: str,  # noqa: ARG001 - retained compat token; reads now relay
    call_domain_sync_fn,
    is_dry_run_fn,
    query_item_status_fn,
) -> bool:
    """Repair a single field drift. Returns True on success.

    Branching is on the drift's typed identity: ``item_id`` (internal
    ``items.id``) selects the backlog path, ``(epic_id, task_num)`` the
    epic-task path. ``drift.ref`` is display-only — it is rendered into
    GitHub-facing titles but never parsed back into an id.
    """
    paired_item = _find_paired_for_drift(drift, paired)
    is_backlog = drift.item_id is not None
    is_epic_task = drift.epic_id is not None and drift.task_num is not None
    num = str(drift.item_id) if is_backlog else ""

    if drift.field == "title" and paired_item:
        if is_backlog:
            repair_title = f"[{drift.ref}] {drift.local}"
        elif is_epic_task:
            repair_title = _epic_task_repair_title(drift)
        else:
            return False

        if is_dry_run_fn():
            print(f"[DRY-RUN] Skipping GitHub: edit title for {drift.ref}")
            return True

        return _edit_issue_title_via_rest(
            project=paired_item.project or "yoke",
            number=int(paired_item.gh_num),
            title=repair_title,
        )

    elif drift.field == "body":
        if is_backlog:
            return call_domain_sync_fn(
                _parent().backlog_github_sync.sync_body,
                num,
                project=paired_item.project if paired_item else "yoke",
            )
        elif is_epic_task:
            return (
                _parent().epic_task_sync.sync_task_body(
                    str(drift.epic_id),
                    int(drift.task_num),
                    stdout=io.StringIO(),
                    stderr=io.StringIO(),
                )
                == 0
            )
        return False

    elif drift.field in (
        "label-status", "label-priority", "label-workflow",
        "label-source", "label-owner",
    ):
        if is_backlog:
            return call_domain_sync_fn(
                _parent().backlog_github_sync.sync_labels,
                num,
                project=paired_item.project if paired_item else "yoke",
            )
        return False

    elif drift.field in ("label-frozen", "label-blocked"):
        if is_backlog:
            kind = "frozen" if drift.field == "label-frozen" else "blocked"
            local_value = drift.local.replace(f"{kind}:", "")
            if is_dry_run_fn():
                print(f"[DRY-RUN] Skipping GitHub: sync-{kind}-label for {drift.ref}")
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
        if is_backlog:
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
                print(f"[DRY-RUN] Skipping GitHub: state change for {drift.ref}")
                return True
            new_state = "closed" if drift.local == "CLOSED" else "open"
            return _set_issue_state_via_rest(
                project=paired_item.project or "yoke",
                number=int(paired_item.gh_num),
                state=new_state,
            )
        return False

    elif drift.field == "comment":
        if is_backlog:
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
