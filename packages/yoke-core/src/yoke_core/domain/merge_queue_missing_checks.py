"""Detect an armed BLOCKED landing whose required checks never reported.

Rules name a detected stop; they never decide whether to stop a landing.
"""

from __future__ import annotations

from dataclasses import replace
from urllib.parse import quote

from yoke_contracts.timestamps import utc_now
from yoke_core.domain.merge_queue_entry_checks import (
    failed_required_checks,
    has_pending_required_check,
)
from yoke_core.domain.merge_queue_landing_refresh import LANDING_RECORD_STALE_SECONDS


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


def missing_checks_recovery(names) -> str:
    checks = ", ".join(names or ()) or "the missing required check (names unreadable)"
    return (
        f"find why {checks}'s workflow did not start: inspect the Actions run "
        "page for the reason, fix it, then push a new commit to retrigger it. "
        "A startup_failure run cannot be rerun on GitHub"
    )


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
            missing_checks=read_missing_check_names(
                ctx,
                readback.state.target_branch or ctx.args.target,
                readback.required_checks,
            ),
        )
    return readback
