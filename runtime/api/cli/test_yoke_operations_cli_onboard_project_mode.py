from __future__ import annotations

import json
from pathlib import Path

import pytest

from runtime.api.cli.project_clone_test_support import allow_local_clone
from runtime.api.cli.project_onboarding_test_helpers import (
    ProjectOnboardApi,
    run_git,
    seed_remote,
    tree_snapshot,
)
from yoke_cli import main as yoke_operations_cli
from yoke_cli.config import onboard_project


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
        "--github-adoption", "backlog-only",
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
        "--github-adoption", "backlog-only",
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
    allow_local_clone(monkeypatch)
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
        "--github-adoption", "backlog-only",
        "--json",
    ])

    payload = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert payload["project_mode"] == "clone-remote"
    assert payload["project_onboarding"]["operation"] == "project.import"
    assert payload["project_onboarding"]["checkout"]["mode"] == "clone-remote"
    assert payload["plan"]["project"]["remote_url"] == str(remote)
    assert not checkout.exists()


def test_clone_remote_rejects_credential_url_before_preview() -> None:
    with pytest.raises(
        onboard_project.OnboardProjectError,
        match="credential-free HTTPS",
    ) as caught:
        onboard_project.project_inputs(
            project_mode=onboard_project.PROJECT_MODE_CLONE_REMOTE,
            project_remote_url=(
                "https://octocat:ghp_must_not_escape@github.com/acme/widget.git"
            ),
            project_checkout="/tmp/widget",
            project_slug="widget",
            project_name="Widget",
            project_org=None,
            project_github_repo="acme/widget",
            project_default_branch="main",
            project_public_item_prefix="WIDG",
            existing_project_id=None,
        )

    assert "ghp_must_not_escape" not in str(caught.value)


@pytest.mark.parametrize("extra_args", [
    [],
    ["--json"],
    ["--yes"],
    ["--yes", "--json"],
])
def test_noninteractive_remote_secret_never_reaches_preview_or_apply_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys,
    extra_args: list[str],
) -> None:
    home = tmp_path / "home"
    config = home / "config.json"
    token = tmp_path / "token"
    token.write_text("actor-token\n", encoding="utf-8")
    sentinel = "ghp_preview_must_not_escape"
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
        "--remote-url", (
            f"https://octocat:{sentinel}@github.com/acme/widget.git"
        ),
        "--checkout", str(tmp_path / "widget"),
        "--project-slug", "widget",
        "--project-name", "Widget",
        "--github-repo", "acme/widget",
        "--default-branch", "main",
        "--public-item-prefix", "WIDG",
        "--github-adoption", "backlog-only",
        *extra_args,
    ])

    captured = capsys.readouterr()
    assert rc != 0
    assert sentinel not in captured.out
    assert sentinel not in captured.err
    assert not config.exists()


def test_scp_like_credential_remote_is_not_treated_as_a_local_path() -> None:
    sentinel = "scp_secret_must_not_escape"
    with pytest.raises(onboard_project.OnboardProjectError) as caught:
        onboard_project.project_inputs(
            project_mode=onboard_project.PROJECT_MODE_CLONE_REMOTE,
            project_remote_url=f"octocat:{sentinel}@github.com:acme/widget.git",
            project_checkout="/tmp/widget",
            project_slug="widget",
            project_name="Widget",
            project_org=None,
            project_github_repo="acme/widget",
            project_default_branch="main",
            project_public_item_prefix="WIDG",
            existing_project_id=None,
        )

    assert sentinel not in str(caught.value)


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
            "--github-adoption", "backlog-only",
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
    assert written["projects"] == [
        {"checkout": str(checkout.resolve()), "project_id": 44, "env": "prod"},
    ]
    assert (checkout / ".yoke/install-manifest.json").is_file()
    assert "actor-token" not in out
    assert "actor-token" not in config.read_text(encoding="utf-8")
