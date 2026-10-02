"""Read-only setup-commit publication preview for onboarding Review."""

from __future__ import annotations

from pathlib import Path
import shlex
from typing import Any

from yoke_cli.config import github_credentials, github_repo_config, machine_config
from yoke_cli.config.project_git_transport import (
    https_remote,
    is_configured_github_remote,
)
from yoke_cli.project_install import publication_reconcile

PLAN_ACTION = "project-setup-publication"


def plan_step(inputs: dict[str, Any], config_path: Path) -> dict[str, str]:
    """Name what the existing publisher will do, without contacting GitHub."""
    checkout = str(inputs.get("checkout") or "")
    root = Path(checkout).expanduser()
    branch = str(inputs.get("default_branch") or "")
    github = machine_config.github_config(config_path)
    remote, url, count = _publish_target(inputs, root, branch)
    if not count:
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
            "Commit locally; not pushed because GitHub is not connected "
            f"(push later with: {command})"
        )
    else:
        text = f"Commit Yoke setup and push to {remote} {branch}"
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
            urls = github_repo_config.values(root, f"remote.{remote}.url")
            return remote, urls[0] if urls else "", count
        return "", "", count
    url = str(inputs.get("remote_url") or "")
    return ("origin", url, 1) if url else ("", "", 0)
