"""Org-targeting coverage for product project onboarding flows."""

from __future__ import annotations

import json
from pathlib import Path

from runtime.api.cli.project_onboarding_test_helpers import (
    ProjectOnboardApi,
    run_git,
    write_https_config,
)
from yoke_cli import main as yoke_operations_cli


def test_project_create_apply_sends_requested_org(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    checkout = tmp_path / "checkouts" / "demo"

    with ProjectOnboardApi() as api:
        config = write_https_config(tmp_path, "product-token", api.url)
        rc = yoke_operations_cli.main([
            "project", "create", str(checkout),
            "--slug", "demo",
            "--name", "Demo",
            "--org", "installer-e2e",
            "--github-repo", "owner/demo",
            "--default-branch", "main",
            "--public-item-prefix", "DMO",
            "--github-adoption", "backlog-only",
            "--config", str(config),
            "--yes",
            "--json",
        ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "project.create"
    create_call = api.function_call("projects.create")
    assert create_call["payload"] == {
        "slug": "demo",
        "name": "Demo",
        "org": "installer-e2e",
        "github_repo": "owner/demo",
        "default_branch": "main",
        "public_item_prefix": "DMO",
        "github_sync_mode": "backlog_only",
    }


def test_onboard_project_dry_run_reports_requested_org(
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
        "--org", "installer-e2e",
        "--github-repo", "owner/local",
        "--default-branch", "main",
        "--public-item-prefix", "LOC",
        "--config", str(config),
        "--dry-run",
        "--json",
    ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "onboard.project"
    assert payload["project"]["org"] == "installer-e2e"
