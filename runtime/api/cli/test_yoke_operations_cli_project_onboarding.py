"""Desired CLI contract for project create/import/onboard flows."""

import json
import subprocess
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

from runtime.api.cli.project_clone_test_support import allow_local_clone
from runtime.api.cli.project_onboarding_test_helpers import (
    ProjectOnboardApi,
    assert_github_preview,
    git_output,
    seed_remote,
    write_https_config,
)
from yoke_cli.config import onboard
from yoke_cli.config import onboard_destinations
from yoke_cli.config import onboard_project
from yoke_cli import main as yoke_operations_cli


def test_project_create_new_repo_binds_identity_and_installs(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    checkout = tmp_path / "checkouts" / "demo"

    with ProjectOnboardApi() as api:
        config = write_https_config(tmp_path, "product-token", api.url)
        config_payload = json.loads(config.read_text(encoding="utf-8"))
        config_payload["github"] = {
            "api_url": "https://api.github.com",
            "web_url": "https://github.com",
            "app_slug": "yoke-test",
            "app_id": 1234,
            "client_id": "Iv1.test",
            "profile_source": "local_explicit",
            "authorization": {
                "kind": "github_app_user_authorization",
                "refresh_credential_ref": "secrets/github-user.json",
                "status": "authorized",
            },
            "installations": [
                {
                    "installation_id": 123,
                    "app_id": 1234,
                    "app_slug": "yoke-test",
                    "account_login": "owner",
                    "account_type": "Organization",
                    "repository_selection": "selected",
                }
            ],
            "repositories": [
                {
                    "repository_id": 456,
                    "installation_id": 123,
                    "full_name": "owner/demo",
                }
            ],
        }
        config.write_text(json.dumps(config_payload), encoding="utf-8")
        monkeypatch.setattr(
            "yoke_cli.config.project_onboard_progress.github_binding_auth.locked_profile_bound_access_for_binding",
            lambda **_kwargs: nullcontext(
                SimpleNamespace(
                    api_url="https://api.github.com",
                    token=SimpleNamespace(access_token="ghu_short_lived"),
                )
            ),
        )
        rc = yoke_operations_cli.main(
            [
                "project",
                "create",
                str(checkout),
                "--slug",
                "demo",
                "--name",
                "Demo",
                "--github-repo",
                "owner/demo",
                "--default-branch",
                "main",
                "--public-item-prefix",
                "DMO",
                "--github-adoption",
                "app-binding",
                "--config",
                str(config),
                "--yes",
                "--json",
            ]
        )

    assert rc == 0
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert payload["operation"] == "project.create"
    assert payload["project"] == {
        "id": 41,
        "slug": "demo",
        "name": "Demo",
        "github_repo": "owner/demo",
        "default_branch": "main",
        "public_item_prefix": "DMO",
    }
    assert payload["checkout"] == {
        "path": str(checkout.resolve()),
        "project_id": 41,
        "registered": True,
    }
    assert payload["install"]["operation"] == "install"
    assert payload["install"]["project_id"] == 41
    assert payload["capabilities"] == {}
    assert payload["github_adoption"] == {
        "choice": "app-binding",
        "explicit": True,
        "preserve_existing": False,
        "github_repo": "owner/demo",
        "automation_enabled": True,
        "requires_explicit_choice": False,
        "binding": {
            "status": "active",
            "repo": "owner/demo",
            "requires_app_installation": True,
        },
    }
    assert_github_preview(payload, enabled=True)

    create_call = api.function_call("projects.create")
    assert create_call["payload"] == {
        "slug": "demo",
        "name": "Demo",
        "github_repo": "owner/demo",
        "default_branch": "main",
        "public_item_prefix": "DMO",
        "github_sync_mode": "backlog_only",
    }
    bind_call = api.function_call("projects.github_binding.bind")
    assert bind_call["payload"] == {
        "project": "41",
        "installation_id": 123,
        "repository_id": 456,
        "github_repo": "owner/demo",
        "expected_api_url": "https://api.github.com",
        "github_user_access_token": "ghu_short_lived",
    }
    sync_mode_call = api.function_call("projects.update")
    assert sync_mode_call["payload"] == {
        "project_id": 41,
        "slug": "demo",
        "name": "Demo",
        "github_sync_mode": "enabled",
    }
    assert api.function_calls("projects.capability_secret.set") == []
    assert api.requests_for("GET", "/v1/projects/41/install-bundle")

    assert (checkout / ".git").is_dir()
    assert git_output(checkout, "branch", "--show-current") == "main"
    # Without --publish, create leaves the checkout local: the repo is inited
    # but no origin is attached (the repo named by --github-repo is recorded as
    # metadata, not created — that happens only on the publish path).
    no_remote = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=checkout,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert no_remote.returncode != 0
    assert (checkout / ".yoke/install-manifest.json").is_file()
    config_payload = json.loads(config.read_text(encoding="utf-8"))
    assert config_payload["projects"] == [
        {"checkout": str(checkout.resolve()), "project_id": 41, "env": "prod"},
    ]


def test_onboard_create_project_permission_denied_is_friendly(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    checkout = tmp_path / "checkouts" / "denied"

    with ProjectOnboardApi(
        project_create_error={
            "code": "permission_denied",
            "message": "permission denied for org acme",
        },
    ) as api:
        config = write_https_config(tmp_path, "product-token", api.url)
        rc = yoke_operations_cli.main(
            [
                "onboard",
                "--config",
                str(config),
                "--env",
                "prod",
                "--api-url",
                api.url,
                "product-token",
                "--yes",
                "--json",
                "--skip-identity-check",
                "--project-mode",
                "create-repo",
                "--checkout",
                str(checkout),
                "--project-slug",
                "demo",
                "--project-name",
                "Demo",
                "--github-repo",
                "owner/demo",
                "--default-branch",
                "main",
                "--public-item-prefix",
                "DMO",
                "--github-adoption",
                "backlog-only",
            ]
        )

    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Your API token lacks project.create rights." in captured.err
    assert "Contact your Yoke administrator." in captured.err
    assert "permission denied for org acme" not in captured.err
    assert "failed step:" in captured.err
    assert "report:" in captured.err
    assert "resume:" in captured.err


def test_project_create_dry_run_rejects_positional_github_token(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    checkout = tmp_path / "checkouts" / "demo"
    token = "ghs_project_positional_secret"

    rc = yoke_operations_cli.main(
        [
            "project",
            "create",
            str(checkout),
            token,
            "--slug",
            "demo",
            "--name",
            "Demo",
            "--github-repo",
            "owner/demo",
            "--default-branch",
            "main",
            "--public-item-prefix",
            "DMO",
            "--config",
            str(tmp_path / "config.json"),
            "--dry-run",
            "--json",
        ]
    )

    assert rc == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unexpected positional argument after CHECKOUT" in captured.err
    assert token not in captured.err


def test_project_create_apply_rejects_positional_github_token(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    checkout = tmp_path / "checkouts" / "direct"
    token = "ghs_project_direct_secret"

    config = write_https_config(tmp_path, "product-token")
    with ProjectOnboardApi():
        rc = yoke_operations_cli.main(
            [
                "project",
                "create",
                str(checkout),
                token,
                "--slug",
                "demo",
                "--name",
                "Demo",
                "--github-repo",
                "owner/demo",
                "--default-branch",
                "main",
                "--public-item-prefix",
                "DMO",
                "--config",
                str(config),
                "--yes",
                "--json",
            ]
        )

    assert rc == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "unexpected positional argument after CHECKOUT" in captured.err
    assert token not in captured.err
    assert not checkout.exists()
    assert token not in config.read_text(encoding="utf-8")


def test_project_import_clones_existing_remote_binds_identity_and_installs(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    remote = seed_remote(tmp_path)
    allow_local_clone(monkeypatch)
    checkout = tmp_path / "checkouts" / "imported"

    with ProjectOnboardApi(
        project={
            "id": 42,
            "slug": "imported",
            "name": "Imported",
            "github_repo": "owner/imported",
            "default_branch": "trunk",
            "public_item_prefix": "IMP",
        },
    ) as api:
        config = write_https_config(tmp_path, "product-token", api.url)
        rc = yoke_operations_cli.main(
            [
                "project",
                "import",
                str(remote),
                str(checkout),
                "--slug",
                "imported",
                "--name",
                "Imported",
                "--github-repo",
                "owner/imported",
                "--default-branch",
                "trunk",
                "--public-item-prefix",
                "IMP",
                "--github-adoption",
                "backlog-only",
                "--config",
                str(config),
                "--yes",
                "--json",
            ]
        )

    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["operation"] == "project.import"
    assert payload["project"]["id"] == 42
    assert payload["project"]["default_branch"] == "trunk"
    assert payload["checkout"] == {
        "path": str(checkout.resolve()),
        "project_id": 42,
        "registered": True,
    }
    assert payload["install"]["operation"] == "install"
    assert payload["install"]["project_id"] == 42

    import_call = api.function_call("projects.create")
    assert import_call["payload"] == {
        "slug": "imported",
        "name": "Imported",
        "github_repo": "owner/imported",
        "default_branch": "trunk",
        "public_item_prefix": "IMP",
        "github_sync_mode": "backlog_only",
    }
    assert (checkout / "README.md").read_text(encoding="utf-8") == ("# imported\n")
    assert git_output(checkout, "remote", "get-url", "origin") == str(remote)
    config_payload = json.loads(config.read_text(encoding="utf-8"))
    assert config_payload["projects"] == [
        {"checkout": str(checkout.resolve()), "project_id": 42, "env": "prod"},
    ]
    assert (checkout / ".yoke/install-manifest.json").is_file()


def test_onboard_existing_project_clone_uses_project_id_without_create(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    remote = seed_remote(tmp_path)
    allow_local_clone(monkeypatch)
    checkout = tmp_path / "checkouts" / "externalwebapp"

    with ProjectOnboardApi(
        project={
            "id": 37,
            "slug": "externalwebapp",
            "name": "ExternalWebapp",
            "github_repo": "example-org/externalwebapp",
            "default_branch": "trunk",
            "public_item_prefix": "EXT",
        },
    ) as api:
        config = write_https_config(tmp_path, "product-token", api.url)
        report = onboard.build_report(
            config_path=config,
            env_name="prod",
            api_url=api.url,
            destination=onboard_destinations.DESTINATION_SERVER,
            token="product-token",
            token_source_kind="argument",
            mode="quick",
            apply=True,
            check_identity=False,
            machine_github_choice="skip",
            project_mode=onboard_project.PROJECT_MODE_CLONE_REMOTE,
            project_remote_url=str(remote),
            project_checkout=checkout,
            project_slug="externalwebapp",
            project_name="ExternalWebapp",
            project_github_repo="example-org/externalwebapp",
            project_default_branch="trunk",
            project_public_item_prefix="EXT",
            existing_project_id=37,
            project_github_adoption="backlog-only",
            project_clone=onboard_project.ClonePlan(),
        )

    project_report = report["project_onboarding"]
    assert project_report["operation"] == "project.clone-existing"
    assert project_report["project"]["id"] == 37
    assert project_report["checkout"] == {
        "path": str(checkout.resolve()),
        "project_id": 37,
        "registered": True,
    }
    assert project_report["install"]["project_id"] == 37
    assert git_output(checkout, "remote", "get-url", "origin") == str(remote)
    assert api.function_calls("projects.create") == []
    assert api.function_call("projects.get")["payload"] == {"project": "37"}
    config_payload = json.loads(config.read_text(encoding="utf-8"))
    assert config_payload["projects"] == [
        {"checkout": str(checkout.resolve()), "project_id": 37, "env": "prod"},
    ]
    assert (checkout / ".yoke/install-manifest.json").is_file()
