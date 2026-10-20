"""Publish setup's board art commit wherever setup's own commit went.

Setup publication runs before the board art exists, so the art commit is
published after it, to the same place: the branch setup pushed to, or the
review branch setup proposed. The result replaces setup's publication outcome
on the report and on its publication step, so a refused push reads pending
with its recovery instead of done. Where setup's commit stayed local, the art
commit stays with it and the recorded recovery says how both reach the remote.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from yoke_cli.config import onboard_apply_late_steps
from yoke_cli.config import onboard_wizard_board_art_apply as art_apply
from yoke_cli.project_install import publication
from yoke_cli.project_install import publication_outcome as outcome_layer
from yoke_cli.project_install import publication_reconcile as reconcile_layer

_LANDED = (outcome_layer.PUBLISHED, outcome_layer.ALREADY_PUBLISHED)


def publish_board_art(
    repo_root: Path,
    onboarding_report: Any,
    receipt: Mapping[str, Any],
    *,
    report_path: str | None = None,
) -> dict[str, Any]:
    """Publish the art commit beside setup's, and re-record the outcome."""
    install = art_apply.install_report(onboarding_report)
    commit = receipt.get("commit")
    commit = commit if isinstance(commit, Mapping) else {}
    if commit.get("status") != "created" or not isinstance(install, dict):
        return {}
    setup = install.get("publication")
    setup = dict(setup) if isinstance(setup, Mapping) else {}
    root = Path(repo_root).expanduser()
    outcome = _art_outcome(root, install, dict(commit), setup)
    install["publication"] = outcome
    path = art_apply.apply_report_path(onboarding_report) or report_path
    if path:
        onboard_apply_late_steps.record_publication_path(path, onboarding_report)
    return outcome


def _art_outcome(
    root: Path,
    install: dict[str, Any],
    commit: dict[str, Any],
    setup: dict[str, Any],
) -> dict[str, Any]:
    status = setup.get("status")
    if status in _LANDED:
        return publication.publish_installed_layer(
            root,
            dict(install),
            commit=commit,
            default_branch=str(setup.get("branch") or ""),
            operation="install",
        )
    art_sha = str(commit.get("sha") or "")
    if setup.get("proposal_branch"):
        return _push_to_review_branch(root, setup, art_sha)
    if status == outcome_layer.SKIPPED:
        # Setup's skip reason (a local-only checkout) holds for the art too.
        return {**setup, "board_art_commit": art_sha}
    remote = str(setup.get("remote") or "") or "<remote>"
    branch = str(setup.get("branch") or "")
    return {
        **setup,
        "board_art_commit": art_sha,
        "recovery": (
            f"{setup.get('recovery') or 'publish setup commit first'}. The board "
            f"art commit {art_sha[:12]} sits on {branch} after setup's commit; "
            f"once setup's commit is on {remote}, `git push {remote} {branch}` "
            "publishes the art too"
        ),
    }


def _push_to_review_branch(
    root: Path,
    setup: dict[str, Any],
    art_sha: str,
) -> dict[str, Any]:
    """Add the art commit to the branch setup proposed for review.

    The review branch is named after setup's commit, so proposing again would
    open a second pull request; a fast-forward push to the recorded branch
    adds the art to the one already proposed.
    """
    remote = str(setup.get("remote") or "")
    branch = str(setup.get("branch") or "")
    review = str(setup["proposal_branch"])
    pushed = reconcile_layer.network_git(
        root, "push", remote, f"{branch}:refs/heads/{review}"
    )
    if pushed.returncode == 0:
        return {
            **setup,
            "commit": outcome_layer.head(root),
            "board_art_commit": art_sha,
        }
    refusal = (pushed.stderr.strip() or pushed.stdout.strip()).strip()
    request = setup.get("pull_request")
    target = (
        str(request.get("url") or "the pull request")
        if isinstance(request, Mapping)
        else review
    )
    outcome = outcome_layer.pending(
        root,
        remote=remote,
        branch=branch,
        detail=f"the board art commit could not be pushed to {review}: {refusal}",
        proposal_branch=review,
        recovery=(
            f"setup's commit is proposed on {review}, but the board art commit "
            f"{art_sha[:12]} is only local. recipe: `git push {remote} "
            f"{branch}:{review}`, which adds it to {target}"
        ),
    )
    if isinstance(request, Mapping):
        outcome["pull_request"] = dict(request)
    return {**outcome, "board_art_commit": art_sha}


__all__ = ["publish_board_art"]
