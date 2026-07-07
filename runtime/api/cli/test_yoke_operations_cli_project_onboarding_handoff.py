"""Project onboarding handoff and root worktree ignore contract tests."""

from __future__ import annotations

import json
from pathlib import Path

from runtime.api.cli.project_onboarding_test_helpers import (
    ProjectOnboardApi,
    run_git,
    write_https_config,
)
from yoke_cli import main as yoke_operations_cli


def test_onboard_project_apply_writes_handoff_and_worktrees_ignore(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    checkout = tmp_path / "local-checkout"
    checkout.mkdir()
    run_git(checkout, "init", "--initial-branch", "main")
    run_git(checkout, "config", "user.email", "tests@example.invalid")
    run_git(checkout, "config", "user.name", "Yoke Tests")
    (checkout / ".gitignore").write_text("node_modules/\n", encoding="utf-8")
    (checkout / "README.md").write_text("# local\n", encoding="utf-8")
    run_git(checkout, "add", ".")
    run_git(checkout, "commit", "-m", "seed local checkout")

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
            "--github-adoption", "temporary-only",
            "--config", str(config),
            "--yes",
            "--json",
        ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["install"]["worktrees_ignore"]["status"] == "written"
    assert payload["install"]["worktrees_ignore"]["patch"] == ["+.worktrees/"]
    assert payload["worktrees_ignore"]["status"] == "present"
    assert payload["worktrees_ignore"]["patch"] == []
    assert (checkout / ".gitignore").read_text(encoding="utf-8") == (
        "node_modules/\n.worktrees/\n"
    )
    assert payload["install"]["snapshot_sync"]["status"] == "ok"
    assert payload["handoff"]["run_id"] == "run-handoff"
    assert payload["handoff"]["install_report"]["project_id"] == 43
    assert "/yoke onboard-project" in payload["handoff"]["agent_command"]

    handoff_call = api.function_call("onboard.checklist.run")
    handoff_payload = handoff_call["payload"]
    assert handoff_payload["project_id"] == 43
    assert handoff_payload["row_status"]["setup-checklist-handoff"] == (
        "configured"
    )
    assert handoff_payload["metadata"]["install_report"]["snapshot_sync"][
        "status"
    ] == "ok"


def test_project_onboard_dry_run_previews_worktrees_ignore_without_writing(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    checkout = tmp_path / "local-checkout"
    checkout.mkdir()
    run_git(checkout, "init", "--initial-branch", "main")
    config = write_https_config(tmp_path, "product-token")

    rc = yoke_operations_cli.main([
        "onboard", "project", str(checkout),
        "--slug", "local",
        "--name", "Local",
        "--default-branch", "main",
        "--public-item-prefix", "LOC",
        "--config", str(config),
        "--dry-run",
        "--json",
    ])

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["worktrees_ignore"] == {
        "path": str(checkout / ".gitignore"),
        "entry": ".worktrees/",
        "present": False,
        "applied": False,
        "patch": ["+.worktrees/"],
        "status": "missing",
    }
    assert not (checkout / ".gitignore").exists()
