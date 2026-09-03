"""Finish-review honesty for Cursor / harness install destinations.

Covers the post-checkout plan lines that name CURSOR.md, .cursor hooks and
permissions, and the machine-local ~/.cursor stop backstop. Split from the
general classifier suite so each authored file stays under the line limit.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("textual")

from yoke_cli.config.onboard_plan_labels import friendly_line
from yoke_contracts import harness_unattended_posture
from yoke_cli.config import machine_registration
from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_report  # noqa: E402
from yoke_cli.config import onboard_reuse_feedback  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402
from yoke_cli.config.project_clone_support import ClonePlan  # noqa: E402

from runtime.api.cli.onboard_wizard_classify_test_support import (  # noqa: E402
    AGENT_RULES_LINE,
    CURSOR_USER_LIFECYCLE_LINE,
    GIT_HOOKS_LINE,
    HARNESS_HOOKS_LINE,
    TOOL_PERMISSIONS_LINE,
    assert_post_checkout_install_destinations,
    build_plan,
    repo_lines,
)


def test_build_plan_clone_make_it_mine_lists_post_checkout_repo_steps() -> None:
    # The clone make-it-mine review must summarize the post-clone work, not just
    # the clone line: re-home + push, install the scaffold, and write board art.
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_CLONE_REMOTE,
        "checkout": "/home/code/widget",
        "github_adoption": None,
        "clone": ClonePlan(outcome="make-it-mine"),
    }
    plan = build_plan(project_inputs, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    repo = repo_lines(plan, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    assert "Clone the project into /home/code/widget" in repo
    assert "Re-home onto the new repo and push" in repo
    assert_post_checkout_install_destinations(
        plan,
        onboard_project.PROJECT_MODE_CLONE_REMOTE,
    )
    assert "Write your board art, rebuild BOARD.md, and commit the art" in repo


def test_build_plan_clone_just_clone_has_no_remote_rehome_step() -> None:
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_CLONE_REMOTE,
        "checkout": "/home/code/widget",
        "github_adoption": None,
        "clone": ClonePlan(outcome="just-clone"),
    }
    plan = build_plan(project_inputs, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    repo = repo_lines(plan, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    # just-clone keeps origin on the source — no re-home / fork remote step.
    assert "Re-home onto the new repo and push" not in repo
    assert "Point origin at your fork and track the source as upstream" not in repo
    assert_post_checkout_install_destinations(
        plan,
        onboard_project.PROJECT_MODE_CLONE_REMOTE,
    )
    assert "Write your board art, rebuild BOARD.md, and commit the art" in repo


def test_build_plan_reused_existing_project_lists_missing_art_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("yoke_cli.config.onboard_session_relay.sys.platform", "linux")
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
        "checkout": "/home/code/externalwebapp",
        "slug": "externalwebapp",
        "name": "ExternalWebapp",
        "github_adoption": "disabled",
        "existing_project_id": 37,
        "github_repo": "owner/externalwebapp",
        "default_branch": "trunk",
        "default_branch_source": (
            onboard_project.DEFAULT_BRANCH_SOURCE_EXISTING_PROJECT
        ),
        "public_item_prefix": "EXT",
    }
    reuse = {
        "yoke_home": True,
        "active_env": True,
        "connection": True,
        "token_reference": True,
        "machine_github": True,
        "aws_admin": True,
        "temp_root": True,
        "cache_dir": True,
        "project_identity": True,
        "project_checkout": True,
        "project_github_auth": True,
        "project_scaffold": True,
    }
    plan = onboard_report.build_plan(
        Path("/home/.yoke/config.json"),
        "prod",
        "https://api.test",
        {"kind": "token_file", "path": "/home/.yoke/secrets/prod.token"},
        {"kind": "token_file", "path": "/home/.yoke/secrets/prod.token"},
        "quick",
        project_mode=onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
        project_inputs=project_inputs,
        machine_github={"choice": "connect"},
        reuse=reuse,
    )
    actions = [step["action"] for step in plan["steps"]]
    grouped = steps.classify_plan(
        {
            "project_mode": onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
            "plan": plan,
        }
    )
    reuse_lines = onboard_reuse_feedback.lines_for_plan(plan)

    assert actions == [
        "register-machine",
        "harness-unattended-posture",
        "project-refresh-scaffold",
        "project-install-agent-rules",
        "project-install-tool-permissions",
        "project-install-harness-hooks",
        "project-install-git-hooks",
        "install-cursor-user-lifecycle-hooks",
        "project-write-board-art",
    ]
    # The posture step is a machine-level write, so it groups beside the
    # Cursor lifecycle hooks rather than with the project's own writes.
    assert grouped["machine"] == [
        friendly_line(machine_registration.REGISTER_ACTION, ""),
        friendly_line(harness_unattended_posture.POSTURE_PLAN_ACTION, "detected"),
        CURSOR_USER_LIFECYCLE_LINE,
    ]
    assert grouped["core"] == []
    assert grouped["repo"] == [
        "Refresh the Yoke project scaffold (.yoke/)",
        AGENT_RULES_LINE,
        TOOL_PERMISSIONS_LINE,
        HARNESS_HOOKS_LINE,
        GIT_HOOKS_LINE,
        "Write your board art, rebuild BOARD.md, and commit the art",
    ]
    assert (
        "Existing Yoke project detected in the Yoke core database: ExternalWebapp (id 37)."
        in reuse_lines
    )
    assert (
        "Existing project GitHub repo in the Yoke core database: owner/externalwebapp."
        in reuse_lines
    )
    assert (
        "Existing project issue prefix in the Yoke core database: EXT." in reuse_lines
    )
    assert (
        "Existing project default branch in the Yoke core database: trunk."
        in reuse_lines
    )
    assert (
        "Checkout mapping is already registered in ~/.yoke/config.json at "
        "/home/code/externalwebapp." in reuse_lines
    )
    assert (
        "Project scaffold is already installed; Apply will refresh it." in reuse_lines
    )
