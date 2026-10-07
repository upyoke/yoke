"""The CLI-manifest gate runs only for a deployment that ships the Yoke CLI."""

from __future__ import annotations

from unittest import mock

from yoke_core.domain import deploy_health_check

from runtime.api.domain.test_deploy_health_check import _dispatch, _stage


def test_repo_that_is_not_a_yoke_source_checkout_skips_manifest_gate(monkeypatch):
    monkeypatch.setattr(
        deploy_health_check, "is_yoke_source_checkout", lambda root: False
    )
    fake_env = mock.Mock()
    fake_env.api_health_url = "https://api.example.com/v1/health"
    fake_env.git_branch = "main"
    with (
        mock.patch(
            "yoke_core.domain.deploy_environment_settings.resolve_deploy_environment",
            return_value=fake_env,
        ),
        mock.patch(
            "yoke_core.domain.deploy_core_container_image.resolve_image_tag",
            return_value="abc123def456",
        ),
        mock.patch.object(
            deploy_health_check._step_runners, "exec_health_check", return_value=0
        ),
        mock.patch.object(
            deploy_health_check, "verify_deployed_cli_manifest"
        ) as manifest,
    ):
        rc, _ = _dispatch(_stage("health-check"))
    assert rc == 0
    manifest.assert_not_called()
