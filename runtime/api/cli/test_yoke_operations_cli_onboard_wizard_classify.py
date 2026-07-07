"""Pure-function coverage for the onboard wizard's write-plan classifier.

``steps.classify_plan`` buckets ``build_report``'s write-plan steps into the
machine / Yoke-core-database / repo-local / source-dev-admin groups the Finish
preview renders. These cases need no Textual pilot, so they live apart from the
pilot-driven flow suite in ``test_yoke_operations_cli_onboard_wizard.py``.
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
from yoke_cli.config.project_clone_support import ClonePlan  # noqa: E402
from yoke_cli.config.project_publish_support import PublishRequest  # noqa: E402


def _step_target(plan: dict, action: str) -> str:
    for step in plan["steps"]:
        if step["action"] == action:
            return step["target"]
    raise AssertionError(f"no {action} step in plan")


def _repo_lines(plan: dict, project_mode: str) -> list[str]:
    """Friendly repo-bucket lines for a ``build_plan`` output.

    ``classify_plan`` consumes the wrapped report shape ``finish_body`` passes it
    (``{"project_mode": ..., "plan": <build_plan output>}``), so wrap the plan the
    same way before classifying.
    """
    report = {"project_mode": project_mode, "plan": plan}
    return steps.classify_plan(report)["repo"]


def _build_plan(project_inputs: dict, project_mode: str) -> dict:
    return onboard_report.build_plan(
        Path("/home/.yoke/config.json"),
        "prod",
        "https://api.test",
        {"kind": "token_file", "path": "/home/.yoke/secrets/prod.token"},
        {"kind": "prompt"},
        "quick",
        project_mode=project_mode,
        project_inputs=project_inputs,
        machine_github={"choice": "skip"},
    )


def test_build_plan_keep_existing_remote_target() -> None:
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
        "checkout": "/home/code/widget",
        "github_adoption": None,
        "keep_existing_remote": True,
    }
    plan = _build_plan(project_inputs, onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)
    assert _step_target(plan, "project-github-auth-choice") == "keep-existing-remote"


def test_build_plan_skip_github_target_when_not_keeping_remote() -> None:
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
        "checkout": "/home/code/widget",
        "github_adoption": None,
        "keep_existing_remote": False,
    }
    plan = _build_plan(project_inputs, onboard_project.PROJECT_MODE_LOCAL_CHECKOUT)
    assert _step_target(plan, "project-github-auth-choice") == "skip"


def test_build_plan_clone_outcome_compound_source_target() -> None:
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_CLONE_REMOTE,
        "checkout": "/home/code/widget",
        "github_adoption": None,
        "clone": ClonePlan(outcome="make-it-mine"),
    }
    plan = _build_plan(project_inputs, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    assert _step_target(plan, "project-source-choice") == "clone-remote:make-it-mine"


def test_build_plan_clone_without_outcome_keeps_bare_mode_target() -> None:
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_CLONE_REMOTE,
        "checkout": "/home/code/widget",
        "github_adoption": None,
        "clone": None,
    }
    plan = _build_plan(project_inputs, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    assert _step_target(plan, "project-source-choice") == "clone-remote"


def test_build_plan_clone_make_it_mine_lists_post_checkout_repo_steps() -> None:
    # The clone make-it-mine review must summarize the post-clone work, not just
    # the clone line: re-home + push, install the scaffold, and write board art.
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_CLONE_REMOTE,
        "checkout": "/home/code/widget",
        "github_adoption": None,
        "clone": ClonePlan(outcome="make-it-mine"),
    }
    plan = _build_plan(project_inputs, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    repo = _repo_lines(plan, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    assert "Clone the project into /home/code/widget" in repo
    assert "Re-home onto the new repo and push" in repo
    assert "Install the Yoke project scaffold (.yoke/)" in repo
    assert "Write your board art and initial BOARD.md" in repo


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
    plan = _build_plan(project_inputs, onboard_project.PROJECT_MODE_CLONE_REMOTE)
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
    plan = _build_plan(project_inputs, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    repo = _repo_lines(plan, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    assert "Point origin at your fork and track the source as upstream" in repo
    assert "Re-home onto the new repo and push" not in repo
    assert "Install the Yoke project scaffold (.yoke/)" in repo


def test_build_plan_clone_just_clone_has_no_remote_rehome_step() -> None:
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_CLONE_REMOTE,
        "checkout": "/home/code/widget",
        "github_adoption": None,
        "clone": ClonePlan(outcome="just-clone"),
    }
    plan = _build_plan(project_inputs, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    repo = _repo_lines(plan, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    # just-clone keeps origin on the source — no re-home / fork remote step.
    assert "Re-home onto the new repo and push" not in repo
    assert "Point origin at your fork and track the source as upstream" not in repo
    # The scaffold + board-art steps still run for every checkout mode.
    assert "Install the Yoke project scaffold (.yoke/)" in repo
    assert "Write your board art and initial BOARD.md" in repo


def test_build_plan_existing_project_missing_board_art_lists_art_step() -> None:
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_CLONE_REMOTE,
        "checkout": "/home/code/buzz",
        "github_adoption": "skip",
        "existing_project_id": 37,
        "clone": ClonePlan(outcome="just-clone"),
    }
    plan = _build_plan(project_inputs, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    actions = {step["action"] for step in plan["steps"]}
    repo = _repo_lines(plan, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    grouped = steps.classify_plan({
        "project_mode": onboard_project.PROJECT_MODE_CLONE_REMOTE,
        "plan": plan,
    })

    assert "project-write-board-art" in actions
    assert "Install the Yoke project scaffold (.yoke/)" in repo
    assert "Write your board art and initial BOARD.md" in repo
    assert grouped["core"][-1] == (
        "Use GitHub settings already stored in the Yoke core database for this "
        "project"
    )


def test_build_plan_existing_project_with_board_art_skips_art_step(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "buzz"
    (checkout / ".yoke").mkdir(parents=True)
    (checkout / ".yoke" / "board-art").write_text("# art\n", encoding="utf-8")
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_CLONE_REMOTE,
        "checkout": str(checkout),
        "github_adoption": "skip",
        "existing_project_id": 37,
        "clone": ClonePlan(outcome="just-clone"),
    }
    plan = _build_plan(project_inputs, onboard_project.PROJECT_MODE_CLONE_REMOTE)
    actions = {step["action"] for step in plan["steps"]}
    repo = _repo_lines(plan, onboard_project.PROJECT_MODE_CLONE_REMOTE)

    assert "project-write-board-art" not in actions
    assert "Install the Yoke project scaffold (.yoke/)" in repo
    assert "Write your board art and initial BOARD.md" not in repo


def test_build_plan_reused_existing_project_lists_missing_art_write() -> None:
    project_inputs = {
        "mode": onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
        "checkout": "/home/code/buzz",
        "slug": "buzz",
        "name": "Buzz",
        "github_adoption": "skip",
        "existing_project_id": 37,
        "github_repo": "owner/buzz",
        "default_branch": "trunk",
        "default_branch_source": (
            onboard_project.DEFAULT_BRANCH_SOURCE_EXISTING_PROJECT
        ),
        "public_item_prefix": "BUZ",
    }
    reuse = {
        "yoke_home": True,
        "active_env": True,
        "connection": True,
        "token_reference": True,
        "machine_github": True,
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
    grouped = steps.classify_plan({
        "project_mode": onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
        "plan": plan,
    })
    reuse_lines = onboard_reuse_feedback.lines_for_plan(plan)

    assert actions == ["project-refresh-scaffold", "project-write-board-art"]
    assert grouped["machine"] == []
    assert grouped["core"] == []
    assert grouped["repo"] == [
        "Refresh the Yoke project scaffold (.yoke/)",
        "Write your board art and initial BOARD.md",
    ]
    assert (
        "Existing Yoke project detected in the Yoke core database: Buzz (id 37)."
        in reuse_lines
    )
    assert (
        "Existing project GitHub repo in the Yoke core database: owner/buzz."
        in reuse_lines
    )
    assert (
        "Existing project issue prefix in the Yoke core database: BUZ."
        in reuse_lines
    )
    assert (
        "Existing project default branch in the Yoke core database: trunk."
        in reuse_lines
    )
    assert (
        "Checkout mapping is already registered in ~/.yoke/config.json at "
        "/home/code/buzz."
        in reuse_lines
    )
    assert "Project scaffold is already installed; Apply will refresh it." in reuse_lines


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
        "github_adoption": "skip",
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
    plan = _build_plan(project_inputs, onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN)
    actions = {step["action"] for step in plan["steps"]}
    assert "project-install-scaffold" not in actions
    assert "project-write-board-art" not in actions


def test_classify_plan_buckets_writes() -> None:
    plan = {
        "project_mode": onboard_project.PROJECT_MODE_CREATE_REPO,
        "plan": {"steps": [
            {"action": "create-or-validate-dir", "target": "/home/.yoke"},
            {"action": "project-create-checkout", "target": "/home/code/demo"},
            {"action": "project-github-auth-choice", "target": "store-token"},
        ]},
    }
    grouped = steps.classify_plan(plan)
    # Each step renders as plain human copy, not the raw action code.
    assert grouped["machine"] == ["Create your Yoke home folder at /home/.yoke"]
    assert grouped["repo"] == ["Create the project at /home/code/demo"]
    assert grouped["core"] == [onboard_github_copy.PROJECT_TOKEN_REVIEW]


def test_classify_plan_source_dev_admin_bucket() -> None:
    plan = {
        "project_mode": onboard_project.PROJECT_MODE_SOURCE_DEV_ADMIN,
        "plan": {"steps": [
            {"action": "project-onboard-local-checkout", "target": "/src/yoke"},
        ]},
    }
    grouped = steps.classify_plan(plan)
    assert grouped["admin"] == ["Set up the project at /src/yoke"]
    assert grouped["repo"] == []


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
            onboard_github_copy.MACHINE_TOKEN_REVIEW,
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
        ("project-write-board-art", ""):
            "Write your board art and initial BOARD.md",
        ("project-source-dev-admin", "/src/yoke"):
            "Set up the Yoke source checkout at /src/yoke",
        ("project-github-auth-choice", "store-token"):
            onboard_github_copy.PROJECT_TOKEN_REVIEW,
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


def test_friendly_line_names_chosen_project_when_known() -> None:
    # With a chosen project name, the source-choice line names it instead of the
    # generic "the project".
    rendered = steps._friendly_line(
        "project-source-choice",
        onboard_project.PROJECT_MODE_CREATE_REPO,
        "Buzz",
    )
    assert rendered == "Record Buzz in the Yoke core database as a new project"


def test_classify_plan_threads_project_name_into_source_choice() -> None:
    plan = {
        "project_mode": onboard_project.PROJECT_MODE_CREATE_REPO,
        "plan": {
            "project": {"name": "Buzz"},
            "steps": [
                {
                    "action": "project-source-choice",
                    "target": onboard_project.PROJECT_MODE_CREATE_REPO,
                },
            ],
        },
    }
    grouped = steps.classify_plan(plan)
    assert grouped["core"] == [
        "Record Buzz in the Yoke core database as a new project"
    ]
