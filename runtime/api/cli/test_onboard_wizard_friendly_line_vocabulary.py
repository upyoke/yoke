"""Exhaustive action-to-human-copy coverage for the onboard wizard.

Asserts every write-plan action ``onboard_report.build_plan`` can emit maps to
a human sentence in ``steps._friendly_line`` (and never leaks a raw action
code). Kept apart from the classifier suite so both stay within the file-line
limit.
"""

from __future__ import annotations

import pytest

pytest.importorskip("textual")

from yoke_cli.config import onboard_github_copy  # noqa: E402
from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402
from yoke_cli.config.project_github_adoption import (  # noqa: E402
    GITHUB_ADOPTION_APP_BINDING,
)


def test_friendly_line_covers_full_action_vocabulary() -> None:
    # Every action onboard_report.build_plan can emit must map to human copy —
    # none may render as a raw action code (action text with a hyphen and no
    # space, e.g. "set-https-api-url: ...").
    cases = {
        ("create-or-validate-dir", "~/.yoke"):
            "Create your Yoke home folder at ~/.yoke",
        ("set-active-env", "prod"): 'Make "prod" your active environment',
        ("set-https-api-url", "https://api.test"): "Connect to https://api.test",
        ("store-token-reference", "prod.token"): "Save your API token (owner-only)",
        ("machine-github-connection", "connect"):
            onboard_github_copy.MACHINE_GITHUB_REVIEW,
        ("machine-github-connection", "skip"): "Skip connecting GitHub for now",
        ("create-runtime-dir", "temp_root"): "Set up the scratch directory",
        ("create-runtime-dir", "cache_dir"): "Set up the cache directory",
        ("project-source-choice", onboard_project.PROJECT_MODE_CREATE_REPO):
            "Record the project in the Yoke core database as a new project",
        ("project-create-checkout", "~/code/demo"): "Create the project at ~/code/demo",
        ("project-clone-remote", "~/code/demo"): "Clone the project into ~/code/demo",
        ("project-import-remote", "~/code/demo"): "Import the project at ~/code/demo",
        ("project-onboard-local-checkout", "~/code/demo"):
            "Set up the project at ~/code/demo",
        ("project-onboard", "~/code/demo"): "Set up the project at ~/code/demo",
        ("project-checkout-register", "~/code/demo"):
            "Register this checkout in ~/.yoke/config.json: ~/code/demo",
        ("project-rehome-push", ""): "Re-home onto the new repo and push",
        ("project-fork-remotes", ""):
            "Point origin at your fork and track the source as upstream",
        ("project-install-scaffold", ""):
            "Install the Yoke project scaffold (.yoke/)",
        ("project-refresh-scaffold", ""):
            "Refresh the Yoke project scaffold (.yoke/)",
        ("project-install-agent-rules", ""):
            "Add Yoke's rules to AGENTS.md, CLAUDE.md, and CODEX.md (keeps any existing content)",
        ("project-install-tool-permissions", ""):
            "Allow Yoke's tools in .claude/settings.json (keeps your other settings)",
        ("project-install-git-hooks", ""):
            "Install Git commit guards (pre-commit, pre-merge-commit, post-commit)",
        ("project-write-board-art", ""):
            "Write your board art and initial BOARD.md",
        ("project-source-dev-admin", "/src/yoke"):
            "Set up the Yoke source checkout at /src/yoke",
        ("project-github-auth-choice", GITHUB_ADOPTION_APP_BINDING):
            onboard_github_copy.PROJECT_GITHUB_REVIEW,
        ("project-github-auth-choice", "skip"):
            "Don't set up Yoke with access to a GitHub remote",
        ("project-github-auth-choice", "keep-existing-remote"):
            "Keep this folder's existing GitHub remote",
        ("project-github-auth-choice", "existing-project"):
            "Use GitHub settings already stored in the Yoke core database for this project",
        # Compound clone-outcome targets refine the clone review line; the legacy
        # bare clone-remote target keeps the original wording (empty suffix).
        ("project-source-choice", "clone-remote"):
            "Record the project in the Yoke core database as a clone of a GitHub repo",
        ("project-source-choice", "clone-remote:make-it-mine"):
            "Record the project in the Yoke core database as a clone of a GitHub repo and re-home it onto a new repo we'll create",
        ("project-source-choice", "clone-remote:fork"):
            "Record the project in the Yoke core database as a clone of a GitHub repo as a fork you can PR back",
        ("project-source-choice", "clone-remote:just-clone"):
            "Record the project in the Yoke core database as a clone of a GitHub repo",
    }
    for (action, target), expected in cases.items():
        rendered = steps._friendly_line(action, target)
        assert rendered == expected, (action, target, rendered)
        # No mapped line may contain a raw "action-code:" prefix.
        assert not rendered.startswith(f"{action}:")
