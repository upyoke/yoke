"""Versioned service-base routing for project onboarding."""

from __future__ import annotations

from pathlib import Path

from runtime.api.cli.project_clone_test_support import allow_local_clone
from runtime.api.cli.project_onboarding_test_helpers import (
    ProjectOnboardApi,
    seed_remote,
    write_https_config,
)
from yoke_cli.config import onboard, onboard_destinations, onboard_project


def test_onboard_existing_project_clone_accepts_versioned_api_url(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine-home"))
    remote = seed_remote(tmp_path)
    allow_local_clone(monkeypatch)
    checkout = tmp_path / "checkouts" / "buzz"

    with ProjectOnboardApi(
        project={
            "id": 37,
            "slug": "buzz",
            "name": "Buzz",
            "github_repo": "example-org/buzz",
            "default_branch": "trunk",
            "public_item_prefix": "BUZZ",
        },
    ) as api:
        versioned_api_url = f"{api.url}/v1"
        config = write_https_config(tmp_path, "product-token", versioned_api_url)
        report = onboard.build_report(
            config_path=config,
            env_name="prod",
            api_url=versioned_api_url,
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
            project_slug="buzz",
            project_name="Buzz",
            project_github_repo="example-org/buzz",
            project_default_branch="trunk",
            project_public_item_prefix="BUZZ",
            existing_project_id=37,
            project_github_adoption="backlog-only",
            project_clone=onboard_project.ClonePlan(),
        )

    assert report["project_onboarding"]["install"]["project_id"] == 37
    assert api.requests_for("GET", "/v1/projects/37/install-bundle")
    assert not any("/v1/v1/" in request["path"] for request in api.requests)
    assert (checkout / ".yoke/install-manifest.json").is_file()
