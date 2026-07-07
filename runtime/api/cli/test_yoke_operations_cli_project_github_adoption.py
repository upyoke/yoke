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


def test_onboard_project_apply_requires_explicit_github_adoption_choice(
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
        "--config", str(config),
        "--yes",
        "--json",
    ])

    assert rc == 1
    err = capsys.readouterr().err
    assert "choose --github-adoption temporary-only" in err


def test_onboard_project_stores_explicit_project_github_token_literal(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    checkout = tmp_path / "local-checkout"
    checkout.mkdir()
    run_git(checkout, "init")
    github_token = tmp_path / "github.token"
    github_token.write_text("ghp_local_project_secret\n", encoding="utf-8")

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
            "--github-adoption", "different-token",
            "--github-token-file", str(github_token),
            "--config", str(config),
            "--yes",
            "--json",
        ])

    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["operation"] == "onboard.project"
    assert payload["applied"] is True
    assert payload["github_adoption"]["choice"] == "different-token"
    assert payload["github_adoption"]["secret"] == {
        "provided": True,
        "import_method": "file",
        "stored": True,
        "storage": "capability_secrets:github.token",
        "persisted_source": "literal",
        "required": True,
    }
    assert_github_preview(payload, enabled=True)
    assert payload["automation_preview"]["project"]["surface"] == "project.upsert"

    get_call = api.function_call("projects.get")
    assert get_call["payload"] == {"project": "local"}
    assert api.function_calls("projects.create") == []
    secret_call = api.function_call("projects.capability_secret.set")
    assert secret_call["payload"] == {
        "project": "local",
        "cap_type": "github",
        "key": "token",
        "value": "ghp_local_project_secret",
        "source": "literal",
    }
    assert "ghp_local_project_secret" not in out
    assert "ghp_local_project_secret" not in tree_text(checkout)
    assert "ghp_local_project_secret" not in config.read_text(encoding="utf-8")


def test_onboard_project_token_store_failure_writes_safe_report(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    checkout = tmp_path / "local-checkout"
    checkout.mkdir()
    run_git(checkout, "init")
    github_token = tmp_path / "github.token"
    github_token.write_text("ghp_local_project_secret\n", encoding="utf-8")

    with ProjectOnboardApi(
        project={
            "id": 43,
            "slug": "local",
            "name": "Local",
            "github_repo": "owner/local",
            "default_branch": "main",
            "public_item_prefix": "LOC",
        },
        capability_secret_error={
            "code": "permission_denied",
            "message": "permission denied storing project GitHub token",
        },
    ) as api:
        config = write_https_config(tmp_path, "product-token", api.url)
        rc = yoke_operations_cli.main([
            "onboard",
            "--config", str(config),
            "--env", "prod",
            "--api-url", api.url,
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
            "--github-adoption", "different-token",
            "--github-token-file", str(github_token),
        ])

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Your API token lacks projects.capability_secret.set rights." in captured.err
    assert "ghp_local_project_secret" not in captured.err
    assert "failed step:" in captured.err
    assert "report:" in captured.err
    assert "resume:" in captured.err

    report_line = next(
        line for line in captured.err.splitlines() if line.startswith("report: ")
    )
    report_path = Path(report_line.removeprefix("report: ").strip())
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    serialized = json.dumps(payload)
    assert payload["final_status"] == "failed"
    assert payload["failed_step"]
    assert payload["resume_command"].startswith("yoke onboard --resume ")
    assert "ghp_local_project_secret" not in serialized
    assert "ghp_local_project_secret" not in tree_text(checkout)
    assert "ghp_local_project_secret" not in config.read_text(encoding="utf-8")


def test_legacy_onboard_project_token_store_failure_is_friendly(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    checkout = tmp_path / "local-checkout"
    checkout.mkdir()
    run_git(checkout, "init")
    github_token = tmp_path / "github.token"
    github_token.write_text("ghp_local_project_secret\n", encoding="utf-8")

    with ProjectOnboardApi(
        project={
            "id": 43,
            "slug": "local",
            "name": "Local",
            "github_repo": "owner/local",
            "default_branch": "main",
            "public_item_prefix": "LOC",
        },
        capability_secret_error={
            "code": "permission_denied",
            "message": "permission denied storing project GitHub token",
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
            "--github-adoption", "different-token",
            "--github-token-file", str(github_token),
            "--config", str(config),
            "--yes",
            "--json",
        ])

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Your API token lacks projects.capability_secret.set rights." in captured.err
    assert "permission denied storing project GitHub token" not in captured.err
    assert "ghp_local_project_secret" not in captured.err
