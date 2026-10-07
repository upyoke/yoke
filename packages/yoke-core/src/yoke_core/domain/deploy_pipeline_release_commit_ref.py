"""The ref a github-actions-workflow stage is dispatched at.

A stage dispatches at its declared ``ref`` branch (default ``main``), so the
workflow file runs from that branch's head while its inputs may pin the run's
bound commit. The ref is a branch of the DEPLOY repo (``github_repo``), not
the product ``gate_branch``: a split deploy/product repo has no product branch
on the deploy side, so it defaults to the deploy repo's own ``main``. A workflow that builds and attests the commit it deploys needs
all three — workflow source, requested ref, and checkout — to be that one
commit, and refuses once the branch has moved past it. A stage declaring
``run_from_release_commit: true`` is therefore dispatched at a lightweight
``yoke-deploy/<run-id>`` tag on the bound commit instead, created through
``github_actions.dispatch_tag.ensure``.

Dispatch tags are retained: a tag is the ref its GitHub workflow runs record,
a re-drive or reconciliation of the same run dispatches at it again, and one
small ref per run is cheap. Nothing deletes them automatically.
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Optional

from yoke_core.domain.flow_validation import RUN_FROM_RELEASE_COMMIT
from yoke_core.domain.handlers.github_actions_dispatch_tag import (
    FUNCTION_ID as DISPATCH_TAG_FUNCTION_ID,
    dispatch_tag_name,
)


def dispatch_ref(
    config: Mapping[str, Any],
    *,
    name: str,
    run_id: str,
    github_repo: str,
    head_sha: str,
    project: str,
    sd: Optional[str],
    github_actions: Callable[..., Any],
) -> tuple[str, str]:
    """``(ref, refusal)`` for dispatching stage ``name``; one of them is empty."""
    if config.get(RUN_FROM_RELEASE_COMMIT) is not True:
        return str(config.get("ref", "") or "main"), ""
    prefix = (
        f"stage {name!r} declares {RUN_FROM_RELEASE_COMMIT} and was not "
        "dispatched: "
    )
    if len(head_sha) != 40:
        return "", (
            f"{prefix}run {run_id} resolved no full release commit to run it "
            f"from (got {head_sha!r}); repair the run's release lineage, then "
            f"re-drive {run_id}"
        )
    tag = dispatch_tag_name(run_id)
    result = github_actions(
        "dispatch-tag", "ensure", github_repo, tag, head_sha,
        project=project, sd=sd,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or "no output"
        return "", (
            f"{prefix}could not tag {head_sha} as {tag} in {github_repo} "
            f"({DISPATCH_TAG_FUNCTION_ID}: {detail}); resolve the named "
            f"refusal, then re-drive {run_id}"
        )
    print(f"  Dispatch ref: tag {tag} on release commit {head_sha}")
    return tag, ""


__all__ = ["RUN_FROM_RELEASE_COMMIT", "dispatch_ref"]
