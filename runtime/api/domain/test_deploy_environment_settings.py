"""Tests for deploy-environment resolution from DB settings snapshots."""

from __future__ import annotations

import pytest

from yoke_core.domain.deploy_environment_settings import (
    DeployEnvironmentError,
    deploy_environment_from_settings,
)
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)


def _settings(
    *,
    environments=(),
    capabilities=None,
) -> ProjectRendererSettings:
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
            "api": "api.example.com",
            "origin": "origin.example.com",
            "origin_port": 80,
        },
        "database": {"name": "yoke_prod"},
        "pulumi": {"stack_name": "yoke-prod", "activation_state": "active"},
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


class TestDeployEnvironmentResolution:
    def test_resolves_full_environment_and_derived_values(self):
        env = deploy_environment_from_settings(
            _settings(
                environments=[_prod_env()],
                capabilities=_full_capabilities(),
            ),
            "prod",
        )
        assert env.project == "yoke"
        assert env.api_host == "api.example.com"
        assert env.origin_host == "origin.example.com"
        assert env.origin_port == 80
        assert env.ssh_target == "ubuntu@origin.example.com"
        assert env.ssh_key_path == "/keys/origin-example.pem"
        assert (
            env.registry_host
            == "123456789012.dkr.ecr.us-east-1.amazonaws.com"
        )
        assert env.image_ref("abc123") == (
            "123456789012.dkr.ecr.us-east-1.amazonaws.com/yoke-core:abc123"
        )
        assert env.api_health_url == "https://api.example.com/v1/health"
        assert env.origin_health_url == "http://origin.example.com/v1/health"
        assert env.compose_dir == "/opt/yoke-core"
        assert env.log_group == "/yoke/prod/core"
        assert env.stack_name == "yoke-prod"
        assert env.activation_state == "active"
        assert env.state_backend == "s3://yoke-pulumi-state?region=us-east-1"
        assert env.database_name == "yoke_prod"
        assert env.otel_exporter_endpoint == ""
        assert env.github_app is None

    def test_resolves_environment_scoped_github_app_secret_reference(self):
        env = deploy_environment_from_settings(
            _settings(
                environments=[_prod_env(github_app={
                    "issuer": "123456",
                    "api_url": "https://api.github.com/",
                    "private_key_secret_arn": (
                        "arn:aws:secretsmanager:us-east-1:123456789012:"
                        "secret:yoke-github-app"
                    ),
                })],
                capabilities=_full_capabilities(),
            ),
            "prod",
        )
        assert env.github_app is not None
        assert env.github_app.issuer == "123456"
        assert env.github_app.api_url == "https://api.github.com"

    @pytest.mark.parametrize(
        "github_app, expected",
        [
            ({"issuer": "123"}, "missing api_url, private_key_secret_arn"),
            ({
                "issuer": "123",
                "api_url": "http://api.github.com",
                "private_key_secret_arn": (
                    "arn:aws:secretsmanager:us-east-1:123:secret:key"
                ),
            }, "must use https"),
            ({
                "issuer": "123",
                "api_url": "https://api.github.com",
                "private_key_secret_arn": "plain-text-is-not-a-reference",
            }, "AWS Secrets Manager ARN"),
        ],
    )
    def test_rejects_incomplete_or_unsafe_github_app_settings(
        self, github_app, expected,
    ):
        with pytest.raises(DeployEnvironmentError, match=expected):
            deploy_environment_from_settings(
                _settings(
                    environments=[_prod_env(github_app=github_app)],
                    capabilities=_full_capabilities(),
                ),
                "prod",
            )

    def test_non_default_origin_port_lands_in_health_url(self):
        env = deploy_environment_from_settings(
            _settings(
                environments=[
                    _prod_env(
                        hosts={
                            "api": "api.example.com",
                            "origin": "origin.example.com",
                            "origin_port": 8080,
                        }
                    )
                ],
                capabilities=_full_capabilities(),
            ),
            "prod",
        )
        assert env.origin_health_url == (
            "http://origin.example.com:8080/v1/health"
        )

    def test_otel_endpoint_passes_through_from_observability_settings(self):
        env = deploy_environment_from_settings(
            _settings(
                environments=[
                    _prod_env(
                        observability={
                            "otel_exporter_endpoint": "https://otel.example/v1"
                        }
                    )
                ],
                capabilities=_full_capabilities(),
            ),
            "prod",
        )
        assert env.otel_exporter_endpoint == "https://otel.example/v1"

    def test_default_user_fallback_for_ssh(self):
        caps = _full_capabilities()
        caps["ssh"] = {
            "default_user": "ubuntu",
            "key_path": "/keys/k.pem",
        }
        env = deploy_environment_from_settings(
            _settings(environments=[_prod_env()], capabilities=caps), "prod"
        )
        assert env.ssh_user == "ubuntu"

    def test_unknown_environment_lists_available(self):
        with pytest.raises(DeployEnvironmentError) as exc:
            deploy_environment_from_settings(
                _settings(
                    environments=[_prod_env()],
                    capabilities=_full_capabilities(),
                ),
                "stage",
            )
        assert "no environment named 'stage'" in str(exc.value)
        assert "available: prod" in str(exc.value)

    @pytest.mark.parametrize(
        "capability",
        ["ssh", "aws-admin", "pulumi-state", "container-registry",
         "webapp-runtime", "health-endpoint"],
    )
    def test_missing_capability_names_sanctioned_write_surface(self, capability):
        caps = _full_capabilities()
        del caps[capability]
        with pytest.raises(DeployEnvironmentError) as exc:
            deploy_environment_from_settings(
                _settings(environments=[_prod_env()], capabilities=caps),
                "prod",
            )
        assert capability in str(exc.value)
        assert "capability-merge-settings" in str(exc.value)

    def test_per_env_ssh_key_path_override_wins_over_capability(self):
        env = deploy_environment_from_settings(
            _settings(
                environments=[
                    _prod_env(
                        servers=[{
                            "host": "1.2.3.4",
                            "ssh_key_path": "/keys/env-override.pem",
                        }]
                    )
                ],
                capabilities=_full_capabilities(),
            ),
            "prod",
        )
        assert env.ssh_key_path == "/keys/env-override.pem"

    def test_per_env_ssh_key_path_works_without_capability_key(self):
        # The capability key_path is only consulted when no per-env
        # override exists — an env with an override resolves even when
        # the ssh capability carries no key_path at all.
        caps = _full_capabilities()
        caps["ssh"] = {"user": "ubuntu"}
        env = deploy_environment_from_settings(
            _settings(
                environments=[
                    _prod_env(
                        servers=[{"ssh_key_path": "/keys/env-override.pem"}]
                    )
                ],
                capabilities=caps,
            ),
            "prod",
        )
        assert env.ssh_key_path == "/keys/env-override.pem"

    def test_servers_without_key_falls_back_to_capability(self):
        for servers in ([{"host": "1.2.3.4"}], [{"ssh_key_path": ""}]):
            env = deploy_environment_from_settings(
                _settings(
                    environments=[_prod_env(servers=servers)],
                    capabilities=_full_capabilities(),
                ),
                "prod",
            )
            assert env.ssh_key_path == "/keys/origin-example.pem"

    def test_no_override_and_no_capability_key_names_ssh_hint(self):
        caps = _full_capabilities()
        caps["ssh"] = {"user": "ubuntu"}
        with pytest.raises(DeployEnvironmentError) as exc:
            deploy_environment_from_settings(
                _settings(environments=[_prod_env()], capabilities=caps),
                "prod",
            )
        assert "'ssh' capability key 'key_path'" in str(exc.value)
        assert "capability-merge-settings" in str(exc.value)

    def test_missing_env_setting_names_environments_home(self):
        env_row = _prod_env(pulumi={})
        with pytest.raises(DeployEnvironmentError) as exc:
            deploy_environment_from_settings(
                _settings(
                    environments=[env_row],
                    capabilities=_full_capabilities(),
                ),
                "prod",
            )
        assert "pulumi.stack_name" in str(exc.value)
        assert "environments.settings" in str(exc.value)


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
        # The narrow reader tolerates env rows that are not deploy-capable
        # (no hosts/pulumi/database) — the merged gate reads any target_env.
        from yoke_core.domain import deploy_environment_settings as des

        bare = RendererEnvironmentSettings(
            id="yoke-api-stage", name="stage",
            settings={"git": {"branch": "stage"}},
        )
        snapshot = _settings(environments=[bare])
        monkeypatch.setattr(
            des, "load_project_renderer_settings", lambda project: snapshot
        )
        assert des.declared_env_branch("yoke", "stage") == "stage"
        assert des.declared_env_branch("yoke", "missing-env") == ""

    def test_declared_env_branch_without_git_key(self, monkeypatch):
        from yoke_core.domain import deploy_environment_settings as des

        bare = RendererEnvironmentSettings(
            id="yoke-api-eph", name="ephemeral", settings={}
        )
        snapshot = _settings(environments=[bare])
        monkeypatch.setattr(
            des, "load_project_renderer_settings", lambda project: snapshot
        )
        assert des.declared_env_branch("yoke", "ephemeral") == ""
