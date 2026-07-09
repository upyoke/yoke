"""Dry-run contract for onboarding an existing local checkout.

Split from ``test_yoke_operations_cli_project_onboarding`` to keep each
module under the per-file line limit. Asserts the dry-run reports the plan
without mutating the checkout or machine config.
"""

import json
from pathlib import Path

from runtime.api.cli.project_onboarding_test_helpers import (
    assert_github_preview,
    run_git,
    tree_snapshot,
    write_https_config,
)
from yoke_cli import main as yoke_operations_cli


def test_onboard_project_dry_run_reports_plan_without_repo_or_config_mutation(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    checkout = tmp_path / "local-checkout"
    checkout.mkdir()
    run_git(checkout, "init")
    (checkout / "README.md").write_text("# local\n", encoding="utf-8")
    before_checkout = tree_snapshot(checkout)
    config = write_https_config(tmp_path, "product-token")
    before_config = config.read_text(encoding="utf-8")

    rc = yoke_operations_cli.main([
        "onboard", "project", str(checkout),
        "--slug", "local",
        "--name", "Local",
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
    assert payload["applied"] is False
    assert payload["project"] == {
        "slug": "local",
        "name": "Local",
        "github_repo": "owner/local",
        "default_branch": "main",
        "public_item_prefix": "LOC",
    }
    assert payload["checkout"] == {
        "path": str(checkout.resolve()),
        "mode": "existing-local",
    }
    assert payload["plan"] == [
        "project.upsert",
        "project.capabilities.configure",
        "project.checkout.register",
        "project.install",
    ]
    assert payload["github_adoption"]["choice"] == "app-binding"
    assert payload["github_adoption"]["requires_explicit_choice"] is False
    assert payload["github_adoption"]["binding"] == {
        "status": "pending_app_connection",
        "repo": "owner/local",
        "requires_app_installation": True,
    }
    assert payload["github_adoption"]["machine_github_credential_promoted"] is False
    assert_github_preview(payload, enabled=True)
    assert tree_snapshot(checkout) == before_checkout
    assert config.read_text(encoding="utf-8") == before_config
    assert not (checkout / ".yoke/install-manifest.json").exists()
