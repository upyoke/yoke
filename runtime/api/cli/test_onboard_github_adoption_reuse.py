"""Existing-project GitHub preservation and explicit-upgrade semantics."""

from __future__ import annotations

from pathlib import Path

from yoke_cli.config import onboard_project
from yoke_cli.config import onboard_reuse_state


def _inputs(*, preserve: bool, keep_remote: bool = False) -> dict:
    return onboard_project.project_inputs(
        project_mode=onboard_project.PROJECT_MODE_LOCAL_CHECKOUT,
        project_remote_url=None,
        project_checkout="/tmp/project",
        project_slug="project",
        project_name="Project",
        project_org=None,
        project_github_repo="example/project",
        project_default_branch="main",
        project_public_item_prefix="PRJ",
        existing_project_id=41,
        project_github_adoption="app-binding",
        project_github_adoption_preserve=preserve,
        project_keep_existing_remote=keep_remote,
    )


def _reuse(tmp_path: Path, inputs: dict) -> dict:
    return onboard_reuse_state.detect(
        cfg_path=tmp_path / "config.json",
        env_name="prod",
        api_url="https://api.example",
        credential_source={},
        source={},
        project_inputs=inputs,
        machine_github={},
    )


def test_discovered_existing_state_preserves_github_authority(tmp_path: Path) -> None:
    assert _reuse(tmp_path, _inputs(preserve=True))["project_github_auth"] is True


def test_explicit_existing_project_binding_is_not_silently_reused(
    tmp_path: Path,
) -> None:
    assert _reuse(tmp_path, _inputs(preserve=False))["project_github_auth"] is False


def test_existing_remote_does_not_claim_server_binding_reuse(tmp_path: Path) -> None:
    assert _reuse(
        tmp_path, _inputs(preserve=False, keep_remote=True),
    )["project_github_auth"] is False
