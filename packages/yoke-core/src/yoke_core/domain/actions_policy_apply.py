"""Converge a repository's Actions policies onto the declared list.

Creates and updates come before deletes, so a policy replaced under a new
name keeps the repository allowed throughout. Every write is verified by
re-reading live state; remaining drift raises.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_core.domain import github_actions_policies_rest as rest
from yoke_core.domain.actions_policy_declaration import (
    diff_policies,
    policy_body,
    policy_drift,
)
from yoke_core.domain.gh_rest_transport import RestAuthError, RestTransportError

ACTIONS_POLICY_ACCESS_RECOVERY = (
    "Grant Administration: write on the GitHub App installation, approve its "
    "updated repository permissions, then retry."
)


def read_live_policies(
    owner: str, repo: str, *, token: str,
) -> list[dict[str, Any]]:
    """Full details of every repository-level Actions policy."""
    try:
        summaries = rest.list_repository_policies(owner, repo, token=token)
        return [
            rest.get_policy(owner, repo, int(row["id"]), token=token)
            for row in summaries
            if isinstance(row.get("id"), int)
        ]
    except RestAuthError as exc:
        raise RestAuthError(
            f"actions policies unreadable for {owner}/{repo}: {exc}. "
            f"{ACTIONS_POLICY_ACCESS_RECOVERY}",
            status=exc.status,
        ) from None


def converge_policies(
    declared: Sequence[Mapping[str, Any]],
    *,
    owner: str,
    repo: str,
    token: str,
    preview: bool,
) -> dict[str, Any]:
    """Plan, and unless previewing apply, the declared Actions policies.

    Returns ``actions``, ``drift_before`` and ``changed``. Raises
    :class:`RestTransportError` on GitHub failures or remaining drift.
    """
    live = read_live_policies(owner, repo, token=token)
    live_by_name = {str(row.get("name") or ""): row for row in live}
    declared_names = {policy["name"] for policy in declared}
    creates = [p for p in declared if p["name"] not in live_by_name]
    updates = [
        (p, live_by_name[p["name"]])
        for p in declared
        if p["name"] in live_by_name and policy_drift(p, live_by_name[p["name"]])
    ]
    deletes = [row for name, row in sorted(live_by_name.items()) if name not in declared_names]

    actions = [f"create actions policy {p['name']!r}" for p in creates]
    actions += [f"update actions policy {p['name']!r} id={row.get('id')}" for p, row in updates]
    actions += [
        f"delete undeclared actions policy {row.get('name')!r} id={row.get('id')}"
        for row in deletes
    ]
    if not actions:
        actions.append(f"actions policies already match ({len(declared)} declared)")
    result: dict[str, Any] = {
        "actions": actions,
        "drift_before": diff_policies(declared, live),
        "changed": bool(creates or updates or deletes),
    }
    if preview or not result["changed"]:
        return result

    try:
        for policy in creates:
            rest.create_policy(owner, repo, policy_body(policy), token=token)
        for policy, row in updates:
            rest.update_policy(owner, repo, int(row["id"]), policy_body(policy), token=token)
        for row in deletes:
            rest.delete_policy(owner, repo, int(row["id"]), token=token)
    except RestAuthError as exc:
        raise RestAuthError(
            f"actions policy write refused for {owner}/{repo}: {exc}. "
            f"{ACTIONS_POLICY_ACCESS_RECOVERY}",
            status=exc.status,
        ) from None

    remaining = diff_policies(declared, read_live_policies(owner, repo, token=token))
    if remaining:
        raise RestTransportError(
            "actions policy apply completed but live state still drifts: "
            + "; ".join(remaining)
        )
    return result


__all__ = [
    "ACTIONS_POLICY_ACCESS_RECOVERY",
    "converge_policies",
    "read_live_policies",
]
