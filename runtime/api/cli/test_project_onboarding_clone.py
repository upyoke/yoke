"""Project clone and import onboarding preserves bound registry identity."""

import pytest
import json
from pathlib import Path

from runtime.api.cli.project_clone_test_support import allow_local_clone
from runtime.api.cli.project_onboarding_test_helpers import (
    ProjectOnboardApi,
    git_output,
    seed_remote,
    write_https_config,
)
from yoke_cli.config import onboard
from yoke_cli.config import onboard_destinations
from yoke_cli.config import onboard_project
from yoke_cli import main as yoke_operations_cli


pytestmark = pytest.mark.usefixtures("stub_onboard_session_relay")


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
                "disabled",
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
        "github_sync_mode": "disabled",
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
            project_github_adoption="disabled",
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
