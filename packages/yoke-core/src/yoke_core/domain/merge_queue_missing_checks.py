"""Detect an armed BLOCKED landing whose required checks never reported.

Rules name a detected stop; they never decide whether to stop a landing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from urllib.parse import quote

from yoke_contracts.timestamps import format_instant, parse_instant, utc_now
from yoke_core.domain.merge_queue_entry_checks import (
    failed_required_checks,
    has_pending_required_check,
)
from yoke_core.domain.merge_queue_landing_refresh import LANDING_RECORD_STALE_SECONDS

#: How long a queued workflow run for the head is waited on before the advice
#: returns to finding why the required check's workflow did not start.
QUEUED_RUN_WAIT_SECONDS = 2 * 60 * 60

_ACTIVE_RUN_STATUSES = frozenset({"queued", "in_progress"})


@dataclass(frozen=True)
class ActiveWorkflowRun:
    """The oldest workflow run for the head that GitHub has not finished."""

    name: str
    status: str
    since: datetime


def missing_checks_stalled(state, checks, *, now=None) -> bool:
    """Decide only from the already-read PR facts, after GitHub's grace."""
    if (
        state is None
        or state.merged
        or state.closed
        or not state.auto_merge_active
        or state.queue_entry_state != "absent"
        or state.merge_state_status.strip().lower() != "blocked"
        or state.auto_merge_enabled_at is None
        or checks is None
        or failed_required_checks(checks)
        or has_pending_required_check(checks)
    ):
        return False
    age = ((now or utc_now()) - state.auto_merge_enabled_at).total_seconds()
    return age > LANDING_RECORD_STALE_SECONDS


def readback_missing_checks_stalled(readback) -> bool:
    member = readback.membership
    return (
        member is not None
        and not member.in_queue
        and missing_checks_stalled(readback.state, readback.required_checks)
    )


def missing_checks_description(readback) -> str:
    if not readback_missing_checks_stalled(readback):
        return ""
    return f", missing-required-checks={','.join(readback.missing_checks or ()) or 'unknown'}"


def missing_checks_recovery(names, active_run=None, *, now=None) -> str:
    checks = ", ".join(names or ()) or "the missing required check (names unreadable)"
    if active_run is not None:
        age = ((now or utc_now()) - active_run.since).total_seconds()
        if age < QUEUED_RUN_WAIT_SECONDS:
            return (
                f"workflow run {active_run.name or 'for this head'} "
                f"{active_run.status.replace('_', ' ')} since "
                f"{format_instant(active_run.since)}; wait for {checks} to "
                "report. GitHub lands it once the run passes; do not push a new "
                "commit"
            )
    return (
        f"find why {checks}'s workflow did not start: inspect the Actions run "
        "page for the reason, fix it, then push a new commit to retrigger it. "
        "A startup_failure run cannot be rerun on GitHub"
    )


def read_active_workflow_run(ctx, head_sha, *, request=None):
    """Best-effort Actions run read by head commit, only after detection.

    A queued run has no jobs yet, so it has no check runs to report.
    """
    from yoke_contracts.github_app_installation_permissions import (
        GITHUB_ACTIONS_READ_PERMISSION_LEVELS,
    )
    from yoke_core.domain.gh_rest_transport import (
        RestRequest,
        RestTransportError,
        request_with_retry,
        split_repo,
    )
    from yoke_core.domain.merge_github_queue import resolve_auth_detail

    auth, error = resolve_auth_detail(ctx, GITHUB_ACTIONS_READ_PERMISSION_LEVELS)
    if auth is None or error or not head_sha:
        return None
    owner, repo = split_repo(auth.repo)
    try:
        response = (request or request_with_retry)(
            RestRequest(
                method="GET",
                path=f"/repos/{owner}/{repo}/actions/runs",
                query={"head_sha": head_sha, "per_page": "100"},
            ),
            token=auth.token,
        )
    except RestTransportError:
        return None
    body = response.body if isinstance(response.body, dict) else {}
    active = []
    for run in body.get("workflow_runs") or ():
        if not isinstance(run, dict) or run.get("status") not in _ACTIVE_RUN_STATUSES:
            continue
        try:
            since = parse_instant(run.get("created_at"))
        except (TypeError, ValueError):
            continue
        active.append(ActiveWorkflowRun(str(run.get("name") or ""), run["status"], since))
    return min(active, key=lambda run: run.since, default=None)


def missing_checks_facts(ctx, branch, checks, head_sha) -> dict:
    """The names and active run a detected stall reports, read together."""
    return {
        "missing_checks": read_missing_check_names(ctx, branch, checks),
        "active_run": read_active_workflow_run(ctx, head_sha),
    }


def read_missing_check_names(ctx, branch, checks, *, request=None):
    """Best-effort ruleset and classic protection read, only after detection."""
    from yoke_contracts.github_app_installation_permissions import (
        GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
    )
    from yoke_core.domain.gh_rest_transport import (
        RestRequest,
        RestTransportError,
        request_with_retry,
        split_repo,
    )
    from yoke_core.domain.merge_github_queue import resolve_auth_detail

    auth, error = resolve_auth_detail(ctx, GITHUB_CONTENTS_READ_PERMISSION_LEVELS)
    if auth is None or error or not branch:
        return None
    owner, repo = split_repo(auth.repo)
    branch = quote(branch, safe="")
    names = set()
    readable = True
    for suffix in (f"rules/branches/{branch}", f"branches/{branch}"):
        try:
            response = (request or request_with_retry)(
                RestRequest(method="GET", path=f"/repos/{owner}/{repo}/{suffix}"),
                token=auth.token,
            )
        except RestTransportError:
            readable = False
            continue
        body = response.body
        if suffix.startswith("rules/"):
            if not isinstance(body, list):
                readable = False
                continue
            for rule in body:
                if not isinstance(rule, dict):
                    readable = False
                    continue
                if rule.get("type") == "required_status_checks":
                    names.update(
                        value["context"]
                        for value in (rule.get("parameters") or {}).get(
                            "required_status_checks", []
                        )
                        if isinstance(value, dict) and value.get("context")
                    )
        elif isinstance(body, dict):
            names.update(
                (
                    (body.get("protection") or {}).get("required_status_checks") or {}
                ).get("contexts", [])
            )
        else:
            readable = False
    reported = {check.name for check in checks or ()}
    missing = tuple(sorted(names - reported))
    return missing if missing else (() if readable else None)


def complete_missing_checks_readback(ctx, pr_number, state, read_checks):
    """Reuse the clock in the existing check projection on the REST route."""
    from yoke_core.domain.merge_github_check_runs import (
        read_required_checks,
        read_pr_landing_and_required_checks,
    )

    if read_checks is read_required_checks:
        projection = read_pr_landing_and_required_checks(ctx, pr_number)
        if projection.state is not None:
            state = replace(
                state, auto_merge_enabled_at=projection.state.auto_merge_enabled_at
            )
        return state, projection.required_checks, projection.checks_error
    checks, error = read_checks(ctx, pr_number)
    return state, checks, error


def name_missing_checks(ctx, readback):
    """Enrich the readback without letting protection reads change admission."""
    member = readback.membership
    if member is None or member.in_queue:
        return readback
    if readback_missing_checks_stalled(readback):
        return replace(
            readback,
            **missing_checks_facts(
                ctx,
                readback.state.target_branch or ctx.args.target,
                readback.required_checks,
                readback.state.head_sha,
            ),
        )
    return readback
