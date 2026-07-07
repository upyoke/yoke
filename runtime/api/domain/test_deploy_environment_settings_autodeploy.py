"""Tests for the per-env auto-deploy-on-push policy reader.

Sibling of ``test_deploy_environment_settings.py`` (same snapshot-projection
pattern) covering ``auto_deploy_envs_from_settings`` /
``auto_deploy_envs_for_branch``: an environment qualifies only when its
``environments.settings`` declare BOTH ``git.branch == <branch>`` AND
``deploy.auto_on_push == true`` (strict JSON boolean; absent = false).
"""

from __future__ import annotations

import pytest

from yoke_core.domain.deploy_environment_settings import (
    auto_deploy_envs_from_settings,
)
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)


def _settings(environments=()) -> ProjectRendererSettings:
    return ProjectRendererSettings(
        project="yoke",
        display_name="Yoke",
        site_id="yoke-api",
        site_settings={},
        primary_environment=environments[0] if environments else None,
        environments=tuple(environments),
        capabilities={},
    )


def _env_row(env_id: str, name: str, settings: dict) -> RendererEnvironmentSettings:
    return RendererEnvironmentSettings(id=env_id, name=name, settings=settings)


def _stage(deploy=None, branch="stage") -> RendererEnvironmentSettings:
    settings: dict = {"git": {"branch": branch}}
    if deploy is not None:
        settings["deploy"] = deploy
    return _env_row("yoke-api-stage", "stage", settings)


class TestAutoDeployEnvs:
    def test_declared_true_on_matching_branch_matches(self):
        snapshot = _settings(
            environments=[_stage(deploy={"auto_on_push": True})]
        )
        assert auto_deploy_envs_from_settings(snapshot, "stage") == ["stage"]

    def test_absent_policy_means_false(self):
        snapshot = _settings(environments=[_stage()])
        assert auto_deploy_envs_from_settings(snapshot, "stage") == []

    def test_wrong_branch_never_matches(self):
        snapshot = _settings(
            environments=[_stage(deploy={"auto_on_push": True})]
        )
        assert auto_deploy_envs_from_settings(snapshot, "main") == []

    @pytest.mark.parametrize("value", [False, "true", 1, None, {}])
    def test_only_strict_json_true_qualifies(self, value):
        snapshot = _settings(
            environments=[_stage(deploy={"auto_on_push": value})]
        )
        assert auto_deploy_envs_from_settings(snapshot, "stage") == []

    def test_empty_branch_never_matches(self):
        # Envs with no declared branch are the ephemeral tier; an empty
        # branch query must not pair with their missing git.branch.
        no_branch = _env_row(
            "yoke-api-eph", "ephemeral", {"deploy": {"auto_on_push": True}}
        )
        snapshot = _settings(environments=[no_branch])
        assert auto_deploy_envs_from_settings(snapshot, "") == []

    def test_only_opted_in_env_matches_among_same_branch_envs(self):
        opted_out = _env_row(
            "yoke-api-canary", "canary", {"git": {"branch": "stage"}}
        )
        snapshot = _settings(
            environments=[
                _stage(deploy={"auto_on_push": True}),
                opted_out,
            ]
        )
        assert auto_deploy_envs_from_settings(snapshot, "stage") == ["stage"]

    def test_loader_wrapper_resolves_through_snapshot(self, monkeypatch):
        from yoke_core.domain import deploy_environment_settings as des

        prod = _env_row("yoke-api-prod", "prod", {"git": {"branch": "main"}})
        snapshot = _settings(
            environments=[prod, _stage(deploy={"auto_on_push": True})]
        )
        monkeypatch.setattr(
            des, "load_project_renderer_settings", lambda project: snapshot
        )
        assert des.auto_deploy_envs_for_branch("yoke", "stage") == ["stage"]
        assert des.auto_deploy_envs_for_branch("yoke", "main") == []
        assert des.auto_deploy_envs_for_branch("yoke", "") == []
