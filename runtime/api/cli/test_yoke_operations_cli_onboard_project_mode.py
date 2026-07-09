from __future__ import annotations

import json
from pathlib import Path

from runtime.api.cli.project_onboarding_test_helpers import (
    ProjectOnboardApi,
    run_git,
    seed_remote,
    tree_snapshot,
)
from yoke_cli import main as yoke_operations_cli


def test_onboard_local_checkout_dry_run_previews_project_handoff(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    home = tmp_path / "home"
    config = home / "config.json"
    checkout = tmp_path / "local-checkout"
    checkout.mkdir()
    run_git(checkout, "init")
    before_checkout = tree_snapshot(checkout)
    token = tmp_path / "token"
    token.write_text("actor-token\n", encoding="utf-8")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))

    rc = yoke_operations_cli.main([
        "onboard",
        "--non-interactive",
        "--advanced",
        "--config", str(config),
        "--env", "prod",
        "--api-url", "https://api.example.test",
        "--token-file", str(token),
        "--project-mode", "local-checkout",
        "--checkout", str(checkout),
        "--project-slug", "local",
        "--project-name", "Local",
        "--github-repo", "owner/local",
        "--default-branch", "main",
        "--public-item-prefix", "LOC",
        "--github-adoption", "skip",
        "--json",
    ])

    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["applied"] is False
    assert payload["project_mode"] == "local-checkout"
    assert payload["plan"]["project_mutation"] is True
    assert payload["plan"]["github_mutation"] is False
    assert payload["project_onboarding"]["operation"] == "onboard.project"
    assert payload["project_onboarding"]["applied"] is False
    assert payload["project_onboarding"]["checkout"] == {
        "path": str(checkout.resolve()),
        "mode": "existing-local",
    }
    assert payload["project_onboarding"]["github_adoption"]["choice"] == "backlog-only"
    assert "/yoke onboard-project" in payload["next_steps"][1]
    assert "actor-token" not in out
    assert not config.exists()
    assert tree_snapshot(checkout) == before_checkout


def test_onboard_create_repo_dry_run_uses_project_create_branch(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    home = tmp_path / "home"
    config = home / "config.json"
    checkout = tmp_path / "new-checkout"
    token = tmp_path / "token"
    token.write_text("actor-token\n", encoding="utf-8")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))

    rc = yoke_operations_cli.main([
        "onboard",
        "--non-interactive",
        "--quick",
        "--config", str(config),
        "--env", "prod",
        "--api-url", "https://api.example.test",
        "--token-file", str(token),
        "--project-mode", "create-repo",
        "--checkout", str(checkout),
        "--project-slug", "created",
        "--project-name", "Created",
        "--github-repo", "owner/created",
        "--default-branch", "main",
        "--public-item-prefix", "NEW",
        "--github-adoption", "skip",
        "--json",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["project_mode"] == "create-repo"
    assert payload["project_onboarding"]["operation"] == "project.create"
    assert payload["project_onboarding"]["checkout"]["mode"] == "new-local"
    assert any(
        step["action"] == "project-create-checkout"
        for step in payload["plan"]["steps"]
    )
    assert not checkout.exists()
    assert not config.exists()


def test_onboard_clone_remote_dry_run_uses_project_import_branch(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    home = tmp_path / "home"
    config = home / "config.json"
    remote = seed_remote(tmp_path)
    checkout = tmp_path / "imported"
    token = tmp_path / "token"
    token.write_text("actor-token\n", encoding="utf-8")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))

    rc = yoke_operations_cli.main([
        "onboard",
        "--non-interactive",
        "--quick",
        "--config", str(config),
        "--env", "prod",
        "--api-url", "https://api.example.test",
        "--token-file", str(token),
        "--project-mode", "clone-remote",
        "--remote-url", str(remote),
        "--checkout", str(checkout),
        "--project-slug", "imported",
        "--project-name", "Imported",
        "--github-repo", "owner/imported",
        "--default-branch", "main",
        "--public-item-prefix", "IMP",
        "--github-adoption", "skip",
        "--json",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["project_mode"] == "clone-remote"
    assert payload["project_onboarding"]["operation"] == "project.import"
    assert payload["project_onboarding"]["checkout"]["mode"] == "clone-remote"
    assert payload["plan"]["project"]["remote_url"] == str(remote)
    assert not checkout.exists()


def test_onboard_yes_writes_machine_config_and_project_handoff(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    home = tmp_path / "home"
    config = home / "config.json"
    checkout = tmp_path / "local-checkout"
    checkout.mkdir()
    run_git(checkout, "init")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))

    with ProjectOnboardApi(
        project={
            "id": 44,
            "slug": "local",
            "name": "Local",
            "github_repo": "owner/local",
            "default_branch": "main",
            "public_item_prefix": "LOC",
        },
    ) as api:
        rc = yoke_operations_cli.main([
            "onboard",
            "actor-token",
            "--non-interactive",
            "--quick",
            "--config", str(config),
            "--env", "prod",
            "--api-url", api.url,
            "--skip-identity-check",
            "--project-mode", "local-checkout",
            "--checkout", str(checkout),
            "--project-slug", "local",
            "--project-name", "Local",
            "--github-repo", "owner/local",
            "--default-branch", "main",
            "--public-item-prefix", "LOC",
            "--github-adoption", "skip",
            "--yes",
            "--json",
        ])

    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["applied"] is True
    assert payload["message"] == "machine config and project handoff written"
    project_report = payload["project_onboarding"]
    assert project_report["applied"] is True
    assert project_report["project"]["id"] == 44
    assert project_report["handoff"]["run_id"] == "run-handoff"
    assert project_report["handoff"]["agent_command"].startswith(
        "/yoke onboard-project --project-root "
    )
    assert project_report["github_adoption"]["choice"] == "backlog-only"

    get_call = api.function_call("projects.get")
    assert get_call["payload"] == {"project": "local"}
    assert api.function_calls("projects.create") == []
    checklist_call = api.function_call("onboard.checklist.run")
    assert checklist_call["payload"]["project_id"] == 44
    assert checklist_call["payload"]["checkout_path"] == str(checkout.resolve())

    written = json.loads(config.read_text(encoding="utf-8"))
    assert written["active_env"] == "prod"
    assert written["projects"][str(checkout.resolve())] == {"project_id": 44}
    assert (checkout / ".yoke/install-manifest.json").is_file()
    assert "actor-token" not in out
    assert "actor-token" not in config.read_text(encoding="utf-8")


def test_legacy_project_github_adoption_rejected_before_machine_write(
    tmp_path: Path, monkeypatch, capsys,
) -> None:
    home = tmp_path / "home"
    config = home / "config.json"
    checkout = tmp_path / "local-checkout"
    checkout.mkdir()
    run_git(checkout, "init")
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(home))

    rc = yoke_operations_cli.main([
        "onboard",
        "actor-token",
        "--non-interactive",
        "--quick",
        "--config", str(config),
        "--env", "prod",
        "--api-url", "http://127.0.0.1:1",
        "--skip-identity-check",
        "--project-mode", "local-checkout",
        "--checkout", str(checkout),
        "--project-slug", "local",
        "--project-name", "Local",
        "--github-repo", "owner/local",
        "--default-branch", "main",
        "--public-item-prefix", "LOC",
        "--github-adoption", "different-token",
        "--yes",
        "--json",
    ])

    assert rc == 1
    assert "--github-adoption different-token is no longer supported" in (
        capsys.readouterr().err
    )
    assert not config.exists()
