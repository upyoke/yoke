"""Declared git.branch on an environment is a deploy-target fact."""

from __future__ import annotations

from yoke_core.domain import deploy_environment_settings as des
from yoke_core.domain.deploy_environment_settings import (
    deploy_environment_from_settings,
)
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)


def _settings(*, environments=(), capabilities=None) -> ProjectRendererSettings:
    return ProjectRendererSettings(
        project="yoke",
        deploy_namespace="yoke",
        display_name="Yoke",
        site_id="yoke-api",
        site_settings={},
        primary_environment=environments[0] if environments else None,
        environments=tuple(environments),
        capabilities=capabilities or {},
    )


def _prod_env(**overrides) -> RendererEnvironmentSettings:
    settings = {
        "hosts": {
            "api": "https://api.example.com",
            "origin": "origin.example.com",
            "origin_port": 80,
        },
        "database": {"name": "yoke_prod"},
        "pulumi": {
            "stack_name": "yoke-prod",
            "origin_vps_stack_name": "yoke-platform-vps",
            "activation_state": "active",
        },
    }
    settings.update(overrides)
    return RendererEnvironmentSettings(
        id="yoke-api-prod", name="prod", settings=settings
    )


def _full_capabilities() -> dict:
    return {
        "ssh": {
            "user": "ubuntu",
            "key_path": "/keys/origin-example.pem",
        },
        "aws-admin": {"region": "us-east-1", "account_id": "123456789012"},
        "pulumi-state": {"state_bucket": "yoke-pulumi-state"},
        "container-registry": {"repository": "yoke-core"},
        "webapp-runtime": {"api_port": 8765},
        "health-endpoint": {"health_path": "/v1/health"},
    }


class TestDeclaredGitBranch:
    """environments.settings.git.branch -> DeployEnvironment.git_branch."""

    def test_declared_branch_populates_git_branch(self):
        env = deploy_environment_from_settings(
            _settings(
                environments=[_prod_env(git={"branch": "main"})],
                capabilities=_full_capabilities(),
            ),
            "prod",
        )
        assert env.git_branch == "main"

    def test_no_git_settings_means_no_declared_branch(self):
        env = deploy_environment_from_settings(
            _settings(
                environments=[_prod_env()],
                capabilities=_full_capabilities(),
            ),
            "prod",
        )
        assert env.git_branch == ""

    def test_declared_env_branch_narrow_reader(self, monkeypatch):
        # The narrow reader tolerates env rows that are not
        # deploy-capable — the merged gate reads any referenced env.
        bare = RendererEnvironmentSettings(
            id="103",
            name="stage",
            settings={"git": {"branch": "stage"}},
        )
        snapshot = _settings(environments=[bare])
        monkeypatch.setattr(
            des, "load_project_renderer_settings", lambda project: snapshot
        )
        assert des.declared_env_branch("yoke", "stage") == "stage"
        assert des.declared_env_branch("yoke", "missing-env") == ""

    def test_declared_env_branch_without_git_key(self, monkeypatch):
        bare = RendererEnvironmentSettings(
            id="yoke-api-eph", name="ephemeral", settings={}
        )
        snapshot = _settings(environments=[bare])
        monkeypatch.setattr(
            des, "load_project_renderer_settings", lambda project: snapshot
        )
        assert des.declared_env_branch("yoke", "yoke-api-eph") == ""
