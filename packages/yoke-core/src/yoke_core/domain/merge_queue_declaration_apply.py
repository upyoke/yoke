"""Apply declared merge-queue config onto a GitHub repository."""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain import github_merge_queue_rest as rest
from yoke_core.domain.gh_rest_transport import RestTransportError
from yoke_core.domain.merge_queue_declaration import (
    diff_declared_against_live,
    ruleset_apply_body,
)


def apply_declaration(
    declared: Mapping[str, Any],
    *,
    owner: str,
    repo: str,
    token: str,
    preview: bool = False,
) -> dict[str, Any]:
    """Idempotently converge live GitHub state onto ``declared``.

    Returns a result dict describing preview or applied mutations. Raises
    :class:`RestTransportError` on GitHub failures.
    """
    ruleset = declared["ruleset"]
    name = str(ruleset["name"])
    body = ruleset_apply_body(ruleset)
    want_auto = bool(declared["repository"]["allow_auto_merge"])
    branch = _branch_from_ruleset(ruleset)

    listed = rest.list_rulesets(owner, repo, token=token)
    existing_id = rest.find_ruleset_id_by_name(listed, name)
    live_rules = rest.fetch_branch_rules(owner, repo, branch, token=token)
    live_repo = rest.fetch_repository(owner, repo, token=token)
    live_auto = live_repo.get("allow_auto_merge")
    live_bypass = None
    compare_bypass = False
    if existing_id is not None:
        try:
            detail = rest.get_ruleset(owner, repo, existing_id, token=token)
            live_bypass = detail.get("bypass_actors")
            compare_bypass = True
        except RestTransportError:
            compare_bypass = False

    drift = diff_declared_against_live(
        declared,
        live_branch_rules=live_rules,
        live_allow_auto_merge=(
            live_auto if isinstance(live_auto, bool) else None
        ),
        live_bypass_actors=live_bypass,
        compare_bypass=compare_bypass,
    )
    missing_ruleset = existing_id is None
    auto_drift = (
        bool(live_auto) != want_auto
        if isinstance(live_auto, bool)
        else True
    )
    ruleset_drift = missing_ruleset or any(
        not line.startswith("allow_auto_merge") for line in drift
    )

    actions: list[str] = []
    if missing_ruleset:
        actions.append(f"create ruleset {name!r}")
    elif ruleset_drift:
        actions.append(f"update ruleset {name!r} id={existing_id}")
    else:
        actions.append(f"ruleset {name!r} already matches")
    if auto_drift:
        actions.append(
            f"set allow_auto_merge={want_auto} (was {live_auto!r})"
        )
    else:
        actions.append(f"allow_auto_merge already {want_auto}")

    result: dict[str, Any] = {
        "preview": preview,
        "owner": owner,
        "repo": repo,
        "ruleset_name": name,
        "ruleset_id": existing_id,
        "actions": actions,
        "drift_before": drift,
        "changed": False,
    }
    if preview:
        result["changed"] = missing_ruleset or ruleset_drift or auto_drift
        return result

    if missing_ruleset:
        created = rest.create_ruleset(owner, repo, body, token=token)
        result["ruleset_id"] = created.get("id")
        result["changed"] = True
    elif ruleset_drift:
        updated = rest.update_ruleset(
            owner, repo, int(existing_id), body, token=token,
        )
        result["ruleset_id"] = updated.get("id", existing_id)
        result["changed"] = True

    if auto_drift:
        rest.patch_allow_auto_merge(
            owner, repo, enabled=want_auto, token=token,
        )
        result["changed"] = True

    remaining = _verify_applied(
        declared,
        owner=owner,
        repo=repo,
        branch=branch,
        ruleset_id=result.get("ruleset_id"),
        token=token,
    )
    result["remaining_drift"] = remaining
    if remaining:
        raise RestTransportError(
            "apply completed but live state still drifts: "
            + "; ".join(remaining)
        )
    return result


def _branch_from_ruleset(ruleset: Mapping[str, Any]) -> str:
    """The branch a ruleset's ref condition names.

    The include pattern is a full ref, so the branch is everything past the
    ``refs/heads/`` boundary. Taking the last slash-separated segment instead
    truncates any branch whose own name contains a slash, and the rules then
    read for a branch that does not exist. Patterns GitHub expresses some
    other way (``~DEFAULT_BRANCH`` and friends) carry no such prefix and pass
    through as written.
    """
    conditions = ruleset.get("conditions") or {}
    ref_name = (
        conditions.get("ref_name") if isinstance(conditions, dict) else None
    )
    if isinstance(ref_name, dict):
        includes = ref_name.get("include") or []
        if includes and isinstance(includes[0], str):
            return includes[0].removeprefix("refs/heads/")
    return "main"


def _verify_applied(
    declared: Mapping[str, Any],
    *,
    owner: str,
    repo: str,
    branch: str,
    ruleset_id: Any,
    token: str,
) -> list[str]:
    live_rules = rest.fetch_branch_rules(owner, repo, branch, token=token)
    live_repo = rest.fetch_repository(owner, repo, token=token)
    live_bypass = None
    compare_bypass = False
    if isinstance(ruleset_id, int):
        try:
            detail = rest.get_ruleset(owner, repo, ruleset_id, token=token)
            live_bypass = detail.get("bypass_actors")
            compare_bypass = True
        except RestTransportError:
            compare_bypass = False
    return diff_declared_against_live(
        declared,
        live_branch_rules=live_rules,
        live_allow_auto_merge=live_repo.get("allow_auto_merge"),
        live_bypass_actors=live_bypass,
        compare_bypass=compare_bypass,
    )


__all__ = ["apply_declaration"]
