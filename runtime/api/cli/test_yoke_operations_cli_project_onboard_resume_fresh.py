"""Fresh clone import coverage for project onboarding."""

from __future__ import annotations

import json
from pathlib import Path

from runtime.api.cli.test_yoke_operations_cli_project_onboard_resume import (
    _allow_local_clone,
)
from runtime.api.cli.project_onboarding_test_helpers import (
    ProjectOnboardApi,
    seed_remote,
    write_https_config,
)
from yoke_cli import main as yoke_operations_cli


def test_fresh_import_carries_no_clone_resume_block(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    _allow_local_clone(monkeypatch)
    remote = seed_remote(tmp_path)
    checkout = tmp_path / "checkouts" / "fresh"
    with ProjectOnboardApi(
        project={
            "id": 78,
            "slug": "fresh",
            "name": "Fresh",
            "github_repo": "owner/fresh",
            "default_branch": "trunk",
            "public_item_prefix": "FRS",
        },
    ) as api:
        config = write_https_config(tmp_path, "product-token", api.url)
        rc = yoke_operations_cli.main(
            [
                "project", "import", str(remote), str(checkout), "--slug", "fresh",
                "--name", "Fresh", "--github-repo", "owner/fresh",
                "--default-branch", "trunk", "--public-item-prefix", "FRS",
                "--github-adoption", "disabled", "--config", str(config),
                "--yes", "--json",
            ]
        )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "project.import"
    assert "clone_resume" not in payload
