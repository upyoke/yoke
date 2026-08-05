"""Shared helpers for onboard wizard write-plan classifier tests."""

from __future__ import annotations

from pathlib import Path

from yoke_cli.config import onboard_report
from yoke_cli.config import onboard_wizard_steps as steps

AGENT_RULES_LINE = (
    "Add Yoke's rules to AGENTS.md, CLAUDE.md, CODEX.md, and CURSOR.md "
    "(keeps any existing content)"
)
TOOL_PERMISSIONS_LINE = (
    "Allow Yoke's tools in .claude/settings.json and "
    ".cursor/cli.json / .cursor/sandbox.json "
    "(keeps your other settings)"
)
HARNESS_HOOKS_LINE = (
    "Install harness hooks in .claude/settings.json, "
    ".codex/hooks.json, and .cursor/hooks.json"
)
GIT_HOOKS_LINE = (
    "Install Git commit guards (pre-commit, pre-merge-commit, post-commit)"
)
CURSOR_USER_LIFECYCLE_LINE = (
    "Install Cursor stop/sessionEnd backstop in ~/.cursor/hooks.json "
    "(survives a deleted project folder)"
)


def step_target(plan: dict, action: str) -> str:
    for step in plan["steps"]:
        if step["action"] == action:
            return step["target"]
    raise AssertionError(f"no {action} step in plan")


def repo_lines(plan: dict, project_mode: str) -> list[str]:
    """Friendly repo-bucket lines for a ``build_plan`` output.

    ``classify_plan`` consumes the wrapped report shape ``finish_body`` passes it
    (``{"project_mode": ..., "plan": <build_plan output>}``), so wrap the plan the
    same way before classifying.
    """
    report = {"project_mode": project_mode, "plan": plan}
    return steps.classify_plan(report)["repo"]


def machine_lines(plan: dict, project_mode: str) -> list[str]:
    report = {"project_mode": project_mode, "plan": plan}
    return steps.classify_plan(report)["machine"]


def build_plan(project_inputs: dict, project_mode: str) -> dict:
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


def assert_post_checkout_install_destinations(
    plan: dict,
    project_mode: str,
    *,
    scaffold_line: str = "Install the Yoke project scaffold (.yoke/)",
) -> None:
    """Assert Finish review names Cursor + harness install destinations."""
    repo = repo_lines(plan, project_mode)
    if scaffold_line:
        assert scaffold_line in repo
    assert AGENT_RULES_LINE in repo
    assert TOOL_PERMISSIONS_LINE in repo
    assert HARNESS_HOOKS_LINE in repo
    assert GIT_HOOKS_LINE in repo
    assert CURSOR_USER_LIFECYCLE_LINE in machine_lines(plan, project_mode)
