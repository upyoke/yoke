"""Setup-commit publication: the Review preview and the Apply outcome.

Review names what the existing publisher will do. Apply records what it did
on the same step, so the run report never reads done for a commit that did
not reach the remote.
"""

from __future__ import annotations

from pathlib import Path
import shlex
from typing import Any, Mapping

from yoke_cli.config import github_credentials, machine_config
from yoke_cli.config.project_git_transport import (
    https_remote,
    is_configured_github_remote,
)
from yoke_cli.project_install import publication_outcome, publication_reconcile

PLAN_ACTION = "project-setup-publication"
FINAL_STATUS_PENDING = "publication-pending"
FINAL_STATUS_SKIPPED = "publication-skipped"
_STEP_STATUS = {
    publication_outcome.PUBLISHED: "done",
    publication_outcome.ALREADY_PUBLISHED: "done",
    publication_outcome.SKIPPED: "skipped",
}
_UNRECORDED = {
    "status": publication_outcome.SKIPPED,
    "reason": "setup recorded no publication outcome for this run",
}


def step_status(publication: Mapping[str, Any] | None) -> str:
    """The apply step status for a publication outcome.

    A commit left local — pending, or proposed for review — is
    ``incomplete``: the step named a push that did not happen, and a resumed
    run tries it again.
    """
    status = str((publication or {}).get("status") or "")
    return _STEP_STATUS.get(status, "incomplete")


def record_outcome(writer: Any, report: Mapping[str, Any]) -> str:
    """Record Apply's publication outcome on its step; return the final status.

    ``final_status`` is plain ``done`` only when the setup commit reached the
    remote, or when this run planned no publication step at all.
    """
    if not writer.has_step(PLAN_ACTION):
        return "done"
    outcome = _applied_outcome(report) or _UNRECORDED
    status = step_status(outcome)
    writer.step_result(
        PLAN_ACTION,
        status,
        detail=outcome,
        error=str(outcome.get("recovery") or "") if status == "incomplete" else None,
    )
    if status == "done":
        return "done"
    return FINAL_STATUS_SKIPPED if status == "skipped" else FINAL_STATUS_PENDING


def _applied_outcome(report: Mapping[str, Any]) -> Mapping[str, Any] | None:
    onboarding = report.get("project_onboarding")
    install = onboarding.get("install") if isinstance(onboarding, Mapping) else None
    outcome = install.get("publication") if isinstance(install, Mapping) else None
    return outcome if isinstance(outcome, Mapping) else None


def plan_step(inputs: dict[str, Any], config_path: Path) -> dict[str, str]:
    """Name what the existing publisher will do, without contacting GitHub."""
    checkout = str(inputs.get("checkout") or "")
    root = Path(checkout).expanduser()
    branch = str(inputs.get("default_branch") or "")
    github = machine_config.github_config(config_path)
    from yoke_cli.config import project_publication_destination as destination
    from yoke_cli.config.project_clone_support import (
        CLONE_OUTCOME_JUST_CLONE, CLONE_OUTCOME_FORK, CLONE_OUTCOME_MAKE_IT_MINE,
    )

    clone = inputs.get("clone")
    remote, url, count = _publish_target(inputs, root, branch)
    if (getattr(clone, "outcome", "") == CLONE_OUTCOME_JUST_CLONE
            or (remote and destination.read_only(root, remote)
                and not getattr(clone, "outcome", ""))):
        text = (
            f"Keep source {url} fetch-only; setup publication pending. "
            + destination.recovery(remote or "origin")
        )
    elif (getattr(clone, "outcome", "") == CLONE_OUTCOME_MAKE_IT_MINE
          and getattr(clone, "publish", None) is None):
        text = (
            "publication_destination_unresolved: Duplicate needs a selected writable "
            "repository. Return to the destination choice before Apply."
        )
    elif getattr(clone, "outcome", "") == CLONE_OUTCOME_FORK:
        text = (
            "Commit Yoke setup and push to the fork selected by GitHub during Apply; "
            "source stays fetch-only upstream. Fork authorization must be confirmed."
        )
    elif not count:
        text = "Commit locally (no remote)"
    elif not remote:
        text = (
            "Commit locally; not pushed because the publication remote is unresolved "
            f"(set the upstream for {branch}, then re-run setup)"
        )
    elif is_configured_github_remote(url, web_url=github.get("web_url")) and not (
        github_credentials.authorization_status(github.get("authorization") or {}).get(
            "present"
        )
    ):
        command = shlex.join(("git", "push", remote, branch))
        text = (
            f"Commit Yoke setup and try to push to {url} ({remote} {branch}) "
            "with your own git credentials (write access unverified); "
            "otherwise commit locally, not pushed because GitHub is not connected "
            f"(push later with: {command})"
        )
    else:
        text = f"Commit Yoke setup and push to {url} ({remote} {branch})"
    return {"action": PLAN_ACTION, "target": text}


def _publish_target(
    inputs: dict[str, Any],
    root: Path,
    branch: str,
) -> tuple[str, str, int]:
    """Use the publisher's resolver, including remotes Apply will create."""
    clone = inputs.get("clone")
    publish = inputs.get("publish") or getattr(clone, "publish", None)
    if publish is not None:
        return "origin", https_remote(publish.full_name, web_url=publish.web_url), 1
    if (root / ".git").exists():
        remote, count = publication_reconcile.resolve_publish_remote(root, branch)
        if remote:
            from yoke_cli.config import project_publication_destination as destination

            urls = destination.push_urls(root, remote)
            if destination.READ_ONLY_PUSH_URL in urls:
                from yoke_cli.config.credentialed_git_command import remote_url

                return remote, remote_url(str(root), remote), count
            return remote, urls[0] if urls else "", count
        return "", "", count
    url = str(inputs.get("remote_url") or "")
    return ("origin", url, 1) if url else ("", "", 0)
