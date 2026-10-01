"""Repository-local identity defaults for automated initial commits."""

from __future__ import annotations

import sys
from pathlib import Path

from yoke_cli.config.project_git_environment import git_config_env
from yoke_cli.config.project_git_process import NetworkGitBoundaryError, run_network_git
from yoke_cli.config.project_git_transport import run_git
from yoke_cli.config.project_onboard_support import ProjectOnboardError

DEFAULT_GIT_IDENTITY = {
    "user.name": "Yoke",
    "user.email": "yoke@example.invalid",
}


def ensure_configured_identity(root: Path) -> None:
    """Fill only missing identity fields; retain local and global preferences."""

    for key, default in DEFAULT_GIT_IDENTITY.items():
        try:
            # This local operation must see global identity preferences, just
            # like the initial commit; network probes deliberately exclude them.
            configured = run_network_git(
                ["git", "config", "--get", key],
                cwd=root,
                env=git_config_env(()),
                timeout_seconds=5,
            )
        except (OSError, NetworkGitBoundaryError) as exc:
            raise ProjectOnboardError(
                f"git_identity_probe_failed: could not read {key}; check Git "
                "configuration and rerun onboarding."
            ) from exc
        if configured.returncode not in (0, 1):
            raise ProjectOnboardError(
                f"git_identity_probe_failed: Git could not read {key}; repair "
                "Git configuration and rerun onboarding."
            )
        if configured.stdout.strip():
            continue
        run_git(root, "config", "--local", key, default)
        print(
            f"Git identity missing {key}; set repository-local default "
            f"{key}={default} in {root}. Global Git configuration is unchanged.",
            file=sys.stderr,
        )
