"""Skip GitHub and clone-from-GitHub copy must stay honest about other forges."""

from __future__ import annotations

from yoke_cli.config import onboard_github_copy
from yoke_cli.config import onboard_plan_labels
from yoke_cli.config import onboard_wizard_project_screens as project_screens
from yoke_cli.config import onboard_wizard_steps as steps


def test_skip_github_copy_names_local_merge_and_disabled_automation() -> None:
    text = " ".join((
        onboard_github_copy.MACHINE_GITHUB_SKIP_DESC,
        onboard_github_copy.MACHINE_GITHUB_SKIP_REVIEW,
        onboard_github_copy.PROJECT_GITHUB_SKIP_DESC,
        onboard_github_copy.PROJECT_GITHUB_SKIP_REVIEW,
        onboard_github_copy.MACHINE_GITHUB_SUBTITLE,
        onboard_github_copy.PROJECT_GITHUB_PROMISE,
    )).casefold()
    assert "local merge" in text
    assert "issues" in text
    assert "merge queue" in text
    assert "app ci" in text


def test_skip_github_rows_use_shared_honesty_copy() -> None:
    skip_rows = (
        steps.MACHINE_GITHUB_ROWS[-1],
        steps.GITHUB_APP_UNAVAILABLE_ROWS[1],
        steps.GITHUB_APP_PENDING_ROWS[1],
        steps.PROJECT_GITHUB_ACCESS_ROWS[1],
        steps.PROJECT_GITHUB_ROWS[-1],
    )
    for row in skip_rows:
        assert "Skip GitHub" in row.label
        assert "merge" in row.hint.casefold()


def test_clone_from_github_copy_does_not_imply_other_forges() -> None:
    clone = " ".join((
        onboard_github_copy.CLONE_FROM_GITHUB_LABEL,
        onboard_github_copy.CLONE_FROM_GITHUB_DESC,
        onboard_github_copy.CLONE_FROM_GITHUB_TITLE,
        onboard_github_copy.CLONE_FROM_GITHUB_SUBTITLE,
        onboard_github_copy.CLONE_VISIBILITY_PUBLIC_DESC,
        steps.MODE_ROWS[1].label,
        steps.MODE_ROWS[1].hint,
        project_screens.CLONE_VISIBILITY_ROWS[0].hint,
    )).casefold()
    assert "github" in clone
    assert "gitlab" in onboard_github_copy.CLONE_FROM_GITHUB_DESC.casefold()
    assert "bitbucket" in onboard_github_copy.CLONE_FROM_GITHUB_DESC.casefold()
    assert "git url" not in clone


def test_review_plan_skip_lines_use_shared_honesty_copy() -> None:
    machine = onboard_plan_labels.friendly_line("machine-github-connection", "skip")
    project = onboard_plan_labels.friendly_line("project-github-auth-choice", "skip")
    assert machine == onboard_github_copy.MACHINE_GITHUB_SKIP_REVIEW
    assert project == onboard_github_copy.PROJECT_GITHUB_SKIP_REVIEW
    assert "local merge" in machine.casefold()
    assert "automation" in project.casefold()
