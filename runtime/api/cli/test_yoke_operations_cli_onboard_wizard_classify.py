"""Pure-function coverage for the onboard wizard's write-plan classifier.

``steps.classify_plan`` buckets ``build_plan``'s write-plan steps into the
machine / Yoke-core-database / repo-local / source-dev-admin groups the Finish
preview renders. These cases need no Textual pilot, so they live apart from the
pilot-driven flow suite in ``test_yoke_operations_cli_onboard_wizard.py``.

Install-destination honesty for Cursor/harness paths lives in
``test_yoke_operations_cli_onboard_wizard_classify_install_destinations``.
"""

from __future__ import annotations

import json

import pytest

pytest.importorskip("textual")

from pathlib import Path  # noqa: E402

from yoke_cli.config import onboard_github_copy  # noqa: E402
from yoke_cli.config import onboard_project  # noqa: E402
from yoke_cli.config import onboard_report  # noqa: E402
from yoke_cli.config import onboard_reuse_feedback  # noqa: E402
from yoke_cli.config import onboard_wizard_steps as steps  # noqa: E402
from yoke_cli.config.project_github_adoption import GITHUB_ADOPTION_APP_BINDING  # noqa: E402
from yoke_cli.config.project_clone_support import ClonePlan  # noqa: E402
from yoke_cli.config.project_publish_support import PublishRequest  # noqa: E402

from runtime.api.cli.onboard_wizard_classify_test_support import (  # noqa: E402
    build_plan,
    repo_lines,
    step_target,
)


def test_build_plan_keep_existing_remote_target() -> None:
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
        "checkout": "/home/code/widget",
        "github_adoption": None,
        "keep_existing_remote": True,
    }
    plan = build_plan(project_inputs, onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)
    assert step_target(plan, "project-github-auth-choice") == "keep-existing-remote"


def test_build_plan_skip_github_target_when_not_keeping_remote() -> None:
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
        "checkout": "/home/code/widget",
        "github_adoption": None,
        "keep_existing_remote": False,
    }
    plan = build_plan(project_inputs, onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)
    assert step_target(plan, "project-github-auth-choice") == "disabled"


def test_build_plan_clone_outcome_compound_source_target() -> None:
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_CLONE_REMOTE,
        "checkout": "/home/code/widget",
        "github_adoption": None,
        "clone": ClonePlan(outcome="make-it-mine"),
    }
    plan = build_plan(project_inputs, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    assert step_target(plan, "project-source-choice") == "clone-remote:make-it-mine"


def test_build_plan_clone_without_outcome_keeps_bare_mode_target() -> None:
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_CLONE_REMOTE,
        "checkout": "/home/code/widget",
        "github_adoption": None,
        "clone": None,
    }
    plan = build_plan(project_inputs, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    assert step_target(plan, "project-source-choice") == "clone-remote"


def test_build_plan_project_payload_sanitizes_clone_publish_secrets() -> None:
    publish = PublishRequest(
        owner="octo-org",
        name="widget-copy",
        user_login="octocat",
        token="publish-secret",
        api_url="https://api.github.example",
        private=True,
    )
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_CLONE_REMOTE,
        "checkout": "/home/code/widget",
        "github_adoption": None,
        "clone": ClonePlan(
            outcome="make-it-mine",
            publish=publish,
            fallback_token="clone-secret",
            fork_api_url="https://api.github.example",
        ),
    }
    plan = build_plan(project_inputs, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    serialized = json.dumps(plan)

    assert "publish-secret" not in serialized
    assert "clone-secret" not in serialized
    assert plan["project"]["clone"]["outcome"] == "make-it-mine"
    assert plan["project"]["clone"]["publish"]["owner"] == "octo-org"


def test_build_plan_clone_fork_lists_fork_remote_step() -> None:
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_CLONE_REMOTE,
        "checkout": "/home/code/widget",
        "github_adoption": None,
        "clone": ClonePlan(outcome="fork"),
    }
    plan = build_plan(project_inputs, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    repo = repo_lines(plan, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    assert "Point origin at your fork and track the source as upstream" in repo
    assert "Re-home onto the new repo and push" not in repo
    assert "Install the Yoke project scaffold (.yoke/)" in repo


def test_build_plan_existing_project_missing_board_art_lists_art_step() -> None:
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_CLONE_REMOTE,
        "checkout": "/home/code/externalwebapp",
        "github_adoption": "disabled",
        "existing_project_id": 37,
        "clone": ClonePlan(outcome="just-clone"),
    }
    plan = build_plan(project_inputs, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    actions = {step["action"] for step in plan["steps"]}
    repo = repo_lines(plan, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    grouped = steps.classify_plan(
        {
            "project_mode": onboard_project.PROJECT_MODE_CLONE_REMOTE,
            "plan": plan,
        }
    )

    assert "project-write-board-art" in actions
    assert "Install the Yoke project scaffold (.yoke/)" in repo
    assert "Write your board art, rebuild BOARD.md, and commit the art" in repo
    assert grouped["core"][-1] == (
        "Use GitHub settings already stored in the Yoke core database for this project"
    )


def test_build_plan_existing_project_with_board_art_skips_art_step(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "externalwebapp"
    (checkout / ".yoke").mkdir(parents=True)
    (checkout / ".yoke" / "board-art").write_text("# art\n", encoding="utf-8")
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_CLONE_REMOTE,
        "checkout": str(checkout),
        "github_adoption": "disabled",
        "existing_project_id": 37,
        "clone": ClonePlan(outcome="just-clone"),
    }
    plan = build_plan(project_inputs, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    actions = {step["action"] for step in plan["steps"]}
    repo = repo_lines(plan, onboard_project.PROJECT_MODE_CLONE_REMOTE)

    assert "project-write-board-art" not in actions
    assert "Install the Yoke project scaffold (.yoke/)" in repo
    assert "Write your board art, rebuild BOARD.md, and commit the art" not in repo


def test_reuse_feedback_names_detected_clone_values() -> None:
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_CLONE_REMOTE,
        "remote_url": "https://github.com/owner/widget.git",
        "checkout": "/home/code/widget",
        "slug": "widget",
        "name": "Widget",
        "github_repo": "owner/widget",
        "default_branch": "trunk",
        "default_branch_source": onboard_project.DEFAULT_BRANCH_SOURCE_SOURCE_REPO,
        "public_item_prefix": "WID",
        "github_adoption": "disabled",
        "clone": ClonePlan(outcome="fork"),
    }
    plan = onboard_report.build_plan(
        Path("/home/.yoke/config.json"),
        "prod",
        "https://api.test",
        {"kind": "token_file", "path": "/home/.yoke/secrets/prod.token"},
        {"kind": "prompt"},
        "quick",
        project_mode=onboard_project.PROJECT_MODE_CLONE_REMOTE,
        project_inputs=project_inputs,
        machine_github={"choice": "skip"},
        reuse={
            "project_clone_checkout": True,
            "project_existing_remote": True,
        },
    )
    reuse_lines = onboard_reuse_feedback.lines_for_plan(plan)

    assert (
        "Matching clone already exists at /home/code/widget; Apply will reuse it."
        in reuse_lines
    )
    assert "Using detected source default branch: trunk." in reuse_lines
    assert "Using this checkout's existing GitHub remote: owner/widget." in reuse_lines


def test_build_plan_source_dev_admin_omits_scaffold_and_board_art() -> None:
    # source-dev-admin uses `yoke dev setup` and never designs board art, so
    # the post-checkout scaffold/board-art steps must not be listed for it.
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN,
        "checkout": "/src/yoke",
        "github_adoption": None,
    }
    plan = build_plan(project_inputs, onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN)
    actions = {step["action"] for step in plan["steps"]}
    assert "project-install-scaffold" not in actions
    assert "project-write-board-art" not in actions


def test_classify_plan_buckets_writes() -> None:
    plan = {
        "project_mode": onboard_project.PROJECT_MODE_CREATE_REPO,
        "plan": {
            "steps": [
                {"action": "create-or-validate-dir", "target": "/home/.yoke"},
                {"action": "project-create-checkout", "target": "/home/code/demo"},
                {
                    "action": "project-github-auth-choice",
                    "target": GITHUB_ADOPTION_APP_BINDING,
                },
            ]
        },
    }
    grouped = steps.classify_plan(plan)
    # Each step renders as plain human copy, not the raw action code.
    assert grouped["machine"] == ["Create your Yoke home folder at /home/.yoke"]
    assert grouped["repo"] == ["Create the project at /home/code/demo"]
    assert grouped["core"] == [onboard_github_copy.PROJECT_GITHUB_REVIEW]


def test_classify_plan_source_dev_admin_bucket() -> None:
    plan = {
        "project_mode": onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN,
        "plan": {
            "steps": [
                {"action": "project-onboard-local-checkout", "target": "/src/yoke"},
            ]
        },
    }
    grouped = steps.classify_plan(plan)
    assert grouped["admin"] == ["Set up the project at /src/yoke"]
    assert grouped["repo"] == []


def test_friendly_line_names_chosen_project_when_known() -> None:
    # With a chosen project name, the source-choice line names it instead of the
    # generic "the project".
    rendered = steps._friendly_line(
        "project-source-choice",
        onboard_project.PROJECT_MODE_CREATE_REPO,
        "ExternalWebapp",
    )
    assert (
        rendered == "Record ExternalWebapp in the Yoke core database as a new project"
    )
