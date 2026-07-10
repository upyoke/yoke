"""GitHub App preflight ordering tests for core-container deployment."""

from __future__ import annotations

from runtime.api.domain.test_deploy_core_container import (
    _env,
    patch_executor_boundaries,
)
from runtime.api.domain.test_deploy_remote import FakeRunner
from yoke_core.domain import github_app_deployment
from yoke_core.domain.deploy_core_container import exec_core_container_deploy
from yoke_core.domain.deploy_remote import CommandResult


class TestGitHubAppPreflight:
    def test_invalid_key_refuses_before_remote_mutation(self, monkeypatch):
        from yoke_core.domain import yoke_cloud_db_authority

        github_app = github_app_deployment
        env = _env(
            github_app=github_app.GitHubAppDeploymentConfig(
                issuer="123456",
                api_url="https://api.github.com",
                private_key_secret_arn=(
                    "arn:aws:secretsmanager:us-east-1:123:secret:github-app"
                ),
            )
        )
        patch_executor_boundaries(monkeypatch, env)
        monkeypatch.setattr(
            yoke_cloud_db_authority,
            "load_secret_string",
            lambda *_args, **_kwargs: "not-a-private-key",
        )
        runner = FakeRunner()

        rc = exec_core_container_deploy(
            "yoke",
            "prod",
            repo_path="/repo",
            runner=runner,
            emit=lambda _line: None,
        )

        assert rc == 1
        assert runner.calls == []

    def test_wrong_live_identity_stops_after_read_only_preflight(
        self,
        monkeypatch,
    ):
        from runtime.api.domain.test_github_app_token_services import (
            _private_key_pair,
        )
        from yoke_core.domain import yoke_cloud_db_authority

        github_app = github_app_deployment
        env = _env(
            github_app=github_app.GitHubAppDeploymentConfig(
                issuer="123456",
                api_url="https://github.internal.example/api/v3",
                private_key_secret_arn=(
                    "arn:aws:secretsmanager:us-east-1:123:secret:github-app"
                ),
            )
        )
        patch_executor_boundaries(monkeypatch, env)
        private_key, _public_key = _private_key_pair()
        monkeypatch.setattr(
            yoke_cloud_db_authority,
            "load_secret_string",
            lambda *_args, **_kwargs: private_key.decode("utf-8"),
        )
        runner = FakeRunner(
            [
                CommandResult(
                    0,
                    '{"id":999,"client_id":"Iv1.other","slug":"other"}',
                    "",
                )
            ]
        )

        rc = exec_core_container_deploy(
            "yoke",
            "prod",
            repo_path="/repo",
            runner=runner,
            emit=lambda _line: None,
        )

        assert rc == 1
        assert len(runner.calls) == 1
        call = runner.calls[0]
        assert call["argv"][0] == "ssh"
        assert call["argv"][-1].endswith(" https://github.internal.example/api/v3/app")
        assert call["input_text"].startswith("ey")
