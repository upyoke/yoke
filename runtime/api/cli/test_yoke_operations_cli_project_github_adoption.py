"""Focused CLI contract for project GitHub adoption choices."""

import json
from pathlib import Path

from runtime.api.cli.project_onboarding_test_helpers import (
    ProjectOnboardApi,
    assert_github_preview,
    run_git,
    tree_text,
    write_https_config,
)
from yoke_cli import main as yoke_operations_cli


def test_onboard_project_defaults_repo_to_app_binding(
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
            "--config", str(config),
            "--yes",
            "--json",
        ])

    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["operation"] == "onboard.project"
    assert payload["applied"] is True
    assert payload["github_adoption"]["choice"] == "app-binding"
    assert payload["github_adoption"]["secret"] == {
        "provided": False,
        "import_method": None,
        "stored": False,
        "storage": None,
        "persisted_source": None,
        "required": False,
    }
    assert payload["github_adoption"]["binding"] == {
        "status": "pending_app_connection",
        "repo": "owner/local",
        "requires_app_installation": True,
    }
    assert_github_preview(payload, enabled=True)
    assert payload["automation_preview"]["project"]["surface"] == "project.upsert"

    get_call = api.function_call("projects.get")
    assert get_call["payload"] == {"project": "local"}
    assert api.function_calls("projects.create") == []
    assert api.function_calls("projects.capability_secret.set") == []


def test_onboard_project_rejects_project_github_token_file(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    checkout = tmp_path / "local-checkout"
    checkout.mkdir()
    run_git(checkout, "init")
    github_token = tmp_path / "github.token"
    github_token.write_text("ghs_local_project_secret\n", encoding="utf-8")

    config = write_https_config(tmp_path, "product-token")
    rc = yoke_operations_cli.main([
        "onboard",
        "--config", str(config),
        "--env", "prod",
        "--api-url", "https://api.example.test",
        "product-token",
        "--yes",
        "--json",
        "--skip-identity-check",
        "--project-mode", "local-checkout",
        "--checkout", str(checkout),
        "--project-slug", "local",
        "--project-name", "Local",
        "--github-repo", "owner/local",
        "--default-branch", "main",
        "--public-item-prefix", "LOC",
        "--github-adoption", "app-binding",
        "--github-token-file", str(github_token),
    ])

    assert rc == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "project-supplied GitHub credentials are no longer supported" in captured.err
    assert "ghs_local_project_secret" not in captured.err
    assert "ghs_local_project_secret" not in tree_text(checkout)
    assert "ghs_local_project_secret" not in config.read_text(encoding="utf-8")


def test_legacy_onboard_project_token_store_failure_is_friendly(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    checkout = tmp_path / "local-checkout"
    checkout.mkdir()
    run_git(checkout, "init")
    config = write_https_config(tmp_path, "product-token")
    rc = yoke_operations_cli.main([
        "onboard", "project", str(checkout),
        "--slug", "local",
        "--name", "Local",
        "--github-repo", "owner/local",
        "--default-branch", "main",
        "--public-item-prefix", "LOC",
        "--github-adoption", "different-token",
        "--config", str(config),
        "--yes",
        "--json",
    ])

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "--github-adoption different-token is no longer supported" in captured.err
