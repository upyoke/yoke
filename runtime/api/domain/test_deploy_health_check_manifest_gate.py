"""The CLI-manifest gate follows the environment's declared serving connection."""

from __future__ import annotations

from unittest import mock

from yoke_core.domain import deploy_health_check
from yoke_core.domain.deploy_cli_manifest_gate import CliManifestGateResult

from runtime.api.domain.test_deploy_health_check import _dispatch, _stage


def _run(serving_connection: str, gate: CliManifestGateResult):
    fake_env = mock.Mock()
    fake_env.api_health_url = "https://api.example.com/v1/health"
    fake_env.git_branch = "main"
    fake_env.serving_connection = serving_connection
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
            deploy_health_check, "verify_deployed_cli_manifest", return_value=gate
        ) as manifest,
    ):
        rc, _ = _dispatch(_stage("health-check"))
    return rc, manifest


def test_environment_without_serving_connection_skips_manifest_gate():
    rc, manifest = _run("", CliManifestGateResult(True, True, "ok"))
    assert rc == 0
    manifest.assert_not_called()


def test_gate_reads_the_declared_serving_connection():
    rc, manifest = _run("prod-api", CliManifestGateResult(True, True, "ok"))
    assert rc == 0
    manifest.assert_called_once_with("prod-api")


def test_declared_connection_this_runner_cannot_check_fails_closed(capsys):
    rc, _ = _run("prod-api", CliManifestGateResult(True, False, "skipped"))
    assert rc == 1
    assert "cli_manifest_gate_unverified" in capsys.readouterr().err
