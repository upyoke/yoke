"""Focused CLI contract for project GitHub adoption choices."""

import json
from pathlib import Path

import pytest

from runtime.api.cli.project_onboarding_test_helpers import (
    ProjectOnboardApi,
    assert_github_preview,
    run_git,
    write_https_config,
)
from yoke_cli import main as yoke_operations_cli
from yoke_cli.config.project_github_adoption import (
    GITHUB_ADOPTION_INPUT_CHOICES,
    ProjectGithubAdoptionError,
    github_adoption_report,
)


def test_retired_skip_alias_is_not_an_adoption_choice() -> None:
    assert GITHUB_ADOPTION_INPUT_CHOICES == ("app-binding", "backlog-only")

    with pytest.raises(ProjectGithubAdoptionError, match="expected one of"):
        github_adoption_report(choice="skip", github_repo="owner/repo", apply=False)


def test_onboard_project_explicit_backlog_only_needs_no_app_binding(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    checkout = tmp_path / "local-checkout"
    checkout.mkdir()
    run_git(checkout, "init")

    with ProjectOnboardApi(
        project={
            "id": 43,
            "slug": "local",
            "name": "Local",
            "github_repo": "owner/local",
            "default_branch": "main",
            "public_item_prefix": "LOC",
        },
    ) as api:
        config = write_https_config(tmp_path, "product-token", api.url)
        rc = yoke_operations_cli.main([
            "onboard", "project", str(checkout),
            "--slug", "local",
            "--name", "Local",
            "--github-repo", "owner/local",
            "--default-branch", "main",
            "--public-item-prefix", "LOC",
            "--github-adoption", "backlog-only",
            "--config", str(config),
            "--yes",
            "--json",
        ])

    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["operation"] == "onboard.project"
    assert payload["applied"] is True
    assert payload["github_adoption"]["choice"] == "backlog-only"
    assert payload["github_adoption"]["binding"] == {
        "status": "skipped",
        "repo": "owner/local",
        "requires_app_installation": False,
    }
    assert_github_preview(payload, enabled=False)
    assert payload["automation_preview"]["project"]["surface"] == "project.upsert"

    get_call = api.function_call("projects.get")
    assert get_call["payload"] == {"project": "local"}
    assert api.function_calls("projects.create") == []
    assert api.function_calls("projects.capability_secret.set") == []
