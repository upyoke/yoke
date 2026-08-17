"""Release-lineage resolution for item-bound deploy-run setup.

Sibling-extracted from :mod:`yoke_core.engines.runs_start_for_item` to keep
the composer under the authored-file line limit and to house the one part of
deploy-run setup that depends on a machine-local Git checkout.

``start_for_item`` runs server-side when its registered function
(``deployment_runs.start_for_item``) is relayed over an https control plane,
and in-process on a local Postgres connection. The flow gate-branch head can
only be read from a machine-local checkout, which the server lacks over
https, so checkout resolution routes through the transport-aware
``checkout_for_project_slug`` and reports :data:`NO_LOCAL_CHECKOUT` when no
checkout is mapped. The two callers branch on that signal:

* An explicit commit ``release_lineage`` (the client already resolved it from
  its own checkout — e.g. the merge SHA ``/yoke dash`` passes) is trusted and
  its exact-remote-head validation is skipped when no local checkout is
  available, so the run starts over https without a checkout. When a checkout
  IS present (the in-process path) the validation runs byte-for-byte as
  before.
* Binding a stage run's lineage from the remote head still requires a
  checkout; without one the caller reports that ``--release-lineage`` must be
  passed explicitly.
"""

from __future__ import annotations

import re
from pathlib import Path


# Placed in the error slot of :func:`_resolve_remote_release_head` when no
# machine-local checkout is mapped for the project (and no explicit
# ``project_repo_path`` was supplied) — the state ``start_for_item`` observes
# running server-side over an https control plane. Callers distinguish it from
# a real resolution failure: lineage validation trusts the client-supplied
# commit and skips, while stage-lineage binding surfaces a
# "pass --release-lineage" error.
NO_LOCAL_CHECKOUT = "no-local-checkout"


def _resolve_remote_release_head(
    project: str,
    target_tier: str,
    target_environment_id: str,
    project_repo_path: str = "",
) -> tuple[str, str]:
    """Read the current flow gate-branch commit from the project remote.

    Returns ``(remote_sha, error)``. ``error`` is :data:`NO_LOCAL_CHECKOUT`
    when no explicit ``project_repo_path`` was given and no machine-local
    checkout is mapped for ``project`` — so callers can tell "no checkout on
    this side of the transport" apart from a genuine resolution failure.
    """
    from yoke_core.domain.deploy_pipeline_gates import resolve_flow_gate_branch
    from yoke_core.domain.deploy_pipeline_github_workflow import (
        _resolve_publish_sha,
    )
    from yoke_core.domain.deploy_pipeline_reporting import _run_cmd
    from yoke_core.domain.project_checkout_locations import (
        checkout_for_project_slug,
    )

    checkout = None
    if project_repo_path:
        candidate = Path(project_repo_path).expanduser().resolve()
        top_level = _run_cmd([
            "git", "-C", str(candidate), "rev-parse", "--show-toplevel",
        ])
        if top_level.returncode != 0 or not top_level.stdout.strip():
            return "", (
                f"project_repo_path '{candidate}' is not a Git checkout"
            )
        resolved_top_level = Path(top_level.stdout.strip()).resolve()
        if resolved_top_level != candidate:
            return "", (
                f"project_repo_path '{candidate}' is not the checkout top-level "
                f"'{resolved_top_level}'"
            )
        status = _run_cmd([
            "git", "-C", str(candidate), "status", "--porcelain",
        ])
        if status.returncode != 0 or status.stdout.strip():
            return "", (
                f"project_repo_path '{candidate}' must be a clean Git checkout"
            )
        project_repo_path = str(candidate)
    else:
        checkout = checkout_for_project_slug(project)
        if checkout is None:
            return "", NO_LOCAL_CHECKOUT

    repo_path = project_repo_path or str(checkout)
    gate_branch = resolve_flow_gate_branch(
        project, target_tier, target_environment_id, repo_path,
    )
    if not gate_branch:
        return "", (
            "deployment flow has no remote gate branch for commit-lineage "
            "validation"
        )
    remote_sha, error = _resolve_publish_sha(repo_path, gate_branch)
    if error:
        return "", error
    return remote_sha, ""


def _validate_commit_release_lineage(
    project: str,
    target_tier: str,
    target_environment_id: str,
    release_lineage: str,
    project_repo_path: str = "",
) -> str:
    """Require an explicit commit lineage to equal the remote release head.

    Returns "" (valid / skip) or an error message. Validation is skipped when
    the lineage is not a full commit SHA, or when no machine-local checkout is
    available to read the remote head from: the client that supplied the exact
    commit already resolved it from its own checkout, so an https control
    plane (server-side, no checkout) trusts the supplied value.
    """
    if not re.fullmatch(r"[0-9a-f]{40}", release_lineage):
        return ""
    remote_sha, error = _resolve_remote_release_head(
        project,
        target_tier,
        target_environment_id,
        project_repo_path,
    )
    if error == NO_LOCAL_CHECKOUT:
        return ""
    if error:
        return error
    if release_lineage != remote_sha:
        return (
            f"release_lineage {release_lineage} does not equal the exact "
            f"remote gate-branch commit {remote_sha}"
        )
    return ""


__all__ = [
    "NO_LOCAL_CHECKOUT",
    "_resolve_remote_release_head",
    "_validate_commit_release_lineage",
]
