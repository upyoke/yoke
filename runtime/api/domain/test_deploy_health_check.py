"""Health-check step runner: readiness plus an exact-candidate build assertion."""

from __future__ import annotations

from unittest import mock

from yoke_core.domain import deploy_health_check, deploy_pipeline_step_runners
from yoke_core.domain.deploy_cli_manifest_gate import CliManifestGateResult


def _dispatch(stage, **overrides):
    kwargs = dict(
        run_id="run-1",
        member_items=["1"],
        github_repo="o/r",
        project="yoke",
        project_repo_path="/repo",
        branch="b",
        first_item="1",
        first_item_label="YOK-1",
        timeout_min=1,
        fresh=False,
        image_tag="",
        environment_name="prod",
        gate_branch="main",
        release_lineage="",
        product_repo_path="",
        sd=None,
    )
    kwargs.update(overrides)
    return deploy_pipeline_step_runners._dispatch_step_runner(stage, **kwargs)


def _stage(step_runner, **config):
    config = {"name": "s", "step_runner": step_runner, **config}
    return {"name": "s", "step_runner": step_runner, "config": config}


def _manifest_gate(ok: bool = True) -> CliManifestGateResult:
    return CliManifestGateResult(ok=ok, checked=True, message="manifest gate")


class TestHealthCheckDispatch:
    def test_explicit_url_skips_env_resolution(self):
        with mock.patch.object(
            deploy_health_check._step_runners,
            "exec_health_check",
            return_value=0,
        ) as health, mock.patch.object(
            deploy_health_check,
            "verify_deployed_cli_manifest",
        ) as manifest:
            rc, _ = _dispatch(_stage("health-check", url="https://x/health"))
        assert rc == 0
        health.assert_called_once_with("https://x/health")
        manifest.assert_not_called()

    def test_resolves_env_url_with_request_id_and_build(self):
        fake_env = mock.Mock()
        fake_env.api_health_url = "https://api.example.com/v1/health"
        fake_env.git_branch = "main"
        fake_env.deploy_namespace = "yoke"
        with mock.patch(
            "yoke_core.domain.deploy_environment_settings."
            "resolve_deploy_environment",
            return_value=fake_env,
        ), mock.patch(
            "yoke_core.domain.deploy_core_container_image."
            "resolve_image_tag",
            return_value="abc123def456",
        ) as resolve, mock.patch.object(
            deploy_health_check._step_runners,
            "exec_health_check",
            return_value=0,
        ) as health, mock.patch.object(
            deploy_health_check,
            "verify_deployed_cli_manifest",
            return_value=_manifest_gate(),
        ) as manifest:
            rc, _ = _dispatch(
                _stage("health-check"), project="platform",
                product_repo_path="/product", member_items=[],
            )
        assert rc == 0
        args, kwargs = health.call_args
        assert args == ("https://api.example.com/v1/health",)
        assert kwargs["request_id"]  # generated, non-empty
        # The gate asserts WHICH code answered: expectation resolved the
        # same way core-deploy resolves its tag.
        assert kwargs["expected_build"] == "abc123def456"
        # ...and that the DB behind it carries the expected schema surface,
        # not just HTTP liveness.
        assert kwargs["require_schema_ready"] is True
        assert resolve.call_args.kwargs["declared_branch"] == "main"
        assert resolve.call_args.args[1] == "/product"
        manifest.assert_called_once_with("prod")

    def test_pinned_lineage_wins_over_repo_state_resolution(self):
        """A run's pinned release_lineage proves the exact candidate; the
        declared branch's current HEAD (which may have moved since this run
        was admitted) must never stand in for it when both are available.
        """
        fake_env = mock.Mock()
        fake_env.api_health_url = "https://api.example.com/v1/health"
        fake_env.git_branch = "main"
        fake_env.deploy_namespace = "yoke"
        lineage = "b" * 40
        with mock.patch(
            "yoke_core.domain.deploy_environment_settings."
            "resolve_deploy_environment",
            return_value=fake_env,
        ), mock.patch(
            "yoke_core.domain.deploy_core_container_image.resolve_image_tag",
        ) as resolve, mock.patch.object(
            deploy_health_check._step_runners,
            "exec_health_check",
            return_value=0,
        ) as health, mock.patch.object(
            deploy_health_check,
            "verify_deployed_cli_manifest",
            return_value=_manifest_gate(),
        ):
            rc, verified_build = _dispatch(
                _stage("health-check"), release_lineage=lineage,
            )
        assert rc == 0
        assert health.call_args.kwargs["expected_build"] == lineage[:12]
        assert verified_build == lineage[:12]
        resolve.assert_not_called()

    def test_no_lineage_falls_back_to_repo_state_resolution(self):
        fake_env = mock.Mock()
        fake_env.api_health_url = "https://api.example.com/v1/health"
        fake_env.git_branch = "main"
        fake_env.deploy_namespace = "yoke"
        with mock.patch(
            "yoke_core.domain.deploy_environment_settings."
            "resolve_deploy_environment",
            return_value=fake_env,
        ), mock.patch(
            "yoke_core.domain.deploy_core_container_image.resolve_image_tag",
            return_value="abc123def456",
        ) as resolve, mock.patch.object(
            deploy_health_check._step_runners,
            "exec_health_check",
            return_value=0,
        ) as health, mock.patch.object(
            deploy_health_check,
            "verify_deployed_cli_manifest",
            return_value=_manifest_gate(),
        ):
            rc, _ = _dispatch(_stage("health-check"), release_lineage="")
        assert rc == 0
        assert health.call_args.kwargs["expected_build"] == "abc123def456"
        resolve.assert_called_once()

    def test_fails_on_manifest_drift(self):
        fake_env = mock.Mock()
        fake_env.api_health_url = "https://api.example.com/v1/health"
        fake_env.git_branch = "main"
        fake_env.deploy_namespace = "yoke"
        with mock.patch(
            "yoke_core.domain.deploy_environment_settings."
            "resolve_deploy_environment",
            return_value=fake_env,
        ), mock.patch(
            "yoke_core.domain.deploy_core_container_image."
            "resolve_image_tag",
            return_value="abc123def456",
        ), mock.patch.object(
            deploy_health_check._step_runners,
            "exec_health_check",
            return_value=0,
        ), mock.patch.object(
            deploy_health_check,
            "verify_deployed_cli_manifest",
            return_value=_manifest_gate(False),
        ):
            rc, _ = _dispatch(_stage("health-check"))
        assert rc == 1

    def test_without_repo_path_skips_build_assertion(self):
        fake_env = mock.Mock()
        fake_env.api_health_url = "https://api.example.com/v1/health"
        fake_env.git_branch = "main"
        fake_env.deploy_namespace = "externalwebapp"
        with mock.patch(
            "yoke_core.domain.deploy_environment_settings."
            "resolve_deploy_environment",
            return_value=fake_env,
        ), mock.patch.object(
            deploy_health_check._step_runners,
            "exec_health_check",
            return_value=0,
        ) as health, mock.patch.object(
            deploy_health_check,
            "verify_deployed_cli_manifest",
            return_value=_manifest_gate(),
        ) as manifest:
            rc, _ = _dispatch(_stage("health-check"), project_repo_path="")
        assert rc == 0
        assert health.call_args.kwargs["expected_build"] == ""
        manifest.assert_not_called()

    def test_uses_pipeline_image_tag_without_repo_path(self):
        fake_env = mock.Mock()
        fake_env.api_health_url = "https://api.example.com/v1/health"
        fake_env.git_branch = "stage"
        with mock.patch(
            "yoke_core.domain.deploy_environment_settings."
            "resolve_deploy_environment",
            return_value=fake_env,
        ), mock.patch.object(
            deploy_health_check._step_runners,
            "exec_health_check",
            return_value=0,
        ) as health, mock.patch.object(
            deploy_health_check,
            "verify_deployed_cli_manifest",
            return_value=_manifest_gate(),
        ):
            rc, _ = _dispatch(
                _stage("health-check"),
                project_repo_path="",
                image_tag="15917b2efb54",
            )
        assert rc == 0
        assert health.call_args.kwargs["expected_build"] == "15917b2efb54"

    def test_unresolvable_tag_skips_build_assertion(self):
        """A repo the tag resolver cannot read degrades to no-assert with a
        printed advisory — never a hard failure of the health stage itself."""
        fake_env = mock.Mock()
        fake_env.api_health_url = "https://api.example.com/v1/health"
        fake_env.git_branch = "main"
        with mock.patch(
            "yoke_core.domain.deploy_environment_settings."
            "resolve_deploy_environment",
            return_value=fake_env,
        ), mock.patch(
            "yoke_core.domain.deploy_core_container_image."
            "resolve_image_tag",
            side_effect=RuntimeError("no repo"),
        ), mock.patch.object(
            deploy_health_check._step_runners,
            "exec_health_check",
            return_value=0,
        ) as health, mock.patch.object(
            deploy_health_check,
            "verify_deployed_cli_manifest",
            return_value=_manifest_gate(),
        ):
            rc, _ = _dispatch(_stage("health-check"))
        assert rc == 0
        assert health.call_args.kwargs["expected_build"] == ""

    def test_env_resolved_fails_when_step_runner_reports_not_ready(self):
        fake_env = mock.Mock()
        fake_env.api_health_url = "https://api.example.com/v1/health"
        fake_env.git_branch = "main"
        with mock.patch(
            "yoke_core.domain.deploy_environment_settings."
            "resolve_deploy_environment",
            return_value=fake_env,
        ), mock.patch(
            "yoke_core.domain.deploy_core_container_image."
            "resolve_image_tag",
            return_value="abc123def456",
        ), mock.patch.object(
            deploy_health_check._step_runners,
            "exec_health_check",
            return_value=1,
        ), mock.patch.object(
            deploy_health_check,
            "verify_deployed_cli_manifest",
        ) as manifest:
            rc, _ = _dispatch(_stage("health-check"))
        assert rc == 1
        manifest.assert_not_called()

    def test_without_url_or_target_env_fails(self):
        rc, _ = _dispatch(_stage("health-check"), environment_name="")
        assert rc == 1
