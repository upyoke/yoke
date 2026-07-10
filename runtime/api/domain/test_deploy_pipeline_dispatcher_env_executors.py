"""Dispatcher tests for the env-aware executors (activate / core-deploy / health)."""

from __future__ import annotations

from unittest import mock

from yoke_core.domain import deploy_pipeline_executors
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
        timeout_min=1,
        fresh=False,
        image_tag="",
        target_env="prod",
        gate_branch="main",
        product_repo_path="",
        sd=None,
    )
    kwargs.update(overrides)
    return deploy_pipeline_executors._dispatch_executor(stage, **kwargs)


def _stage(executor, **config):
    config = {"name": "s", "executor": executor, **config}
    return {"name": "s", "executor": executor, "config": config}


def _manifest_gate(ok: bool = True) -> CliManifestGateResult:
    return CliManifestGateResult(ok=ok, checked=True, message="manifest gate")


class TestEnvExecutorDispatch:
    def test_environment_activate_receives_project_and_target_env(self):
        with mock.patch(
            "yoke_core.domain.deploy_environment_activate."
            "exec_environment_activate",
            return_value=0,
        ) as activate:
            rc, diag = _dispatch(_stage("environment-activate"))
        assert (rc, diag) == (0, "")
        activate.assert_called_once_with("yoke", "prod")

    def test_core_container_deploy_receives_repo_and_tag(self):
        with mock.patch(
            "yoke_core.domain.deploy_core_container."
            "exec_core_container_deploy",
            return_value=0,
        ) as deploy:
            rc, _diag = _dispatch(
                _stage("core-container-deploy", image_tag="abc123")
            )
        assert rc == 0
        deploy.assert_called_once_with(
            "yoke", "prod", repo_path="/repo", image_tag="abc123"
        )

    def test_core_container_deploy_uses_pipeline_image_tag(self):
        with mock.patch(
            "yoke_core.domain.deploy_core_container."
            "exec_core_container_deploy",
            return_value=0,
        ) as deploy:
            rc, _diag = _dispatch(
                _stage("core-container-deploy"),
                project_repo_path="",
                image_tag="15917b2efb54",
            )
        assert rc == 0
        deploy.assert_called_once_with(
            "yoke", "prod", repo_path="", image_tag="15917b2efb54"
        )

    def test_core_container_deploy_uses_itemless_product_checkout(self):
        with mock.patch(
            "yoke_core.domain.deploy_core_container.exec_core_container_deploy",
            return_value=0,
        ) as deploy:
            rc, _ = _dispatch(
                _stage("core-container-deploy"),
                project="platform", product_repo_path="/product",
                image_tag="15917b2efb54", member_items=[],
            )
        assert rc == 0
        deploy.assert_called_once_with(
            "platform", "prod", repo_path="/product", image_tag="15917b2efb54",
        )

    def test_core_container_deploy_stage_config_tag_wins(self):
        with mock.patch(
            "yoke_core.domain.deploy_core_container."
            "exec_core_container_deploy",
            return_value=0,
        ) as deploy:
            rc, _diag = _dispatch(
                _stage("core-container-deploy", image_tag="stage-config"),
                image_tag="pipeline-tag",
            )
        assert rc == 0
        deploy.assert_called_once_with(
            "yoke", "prod", repo_path="/repo", image_tag="stage-config"
        )

    def test_distribution_publish_keeps_owner_and_product_sources_separate(self):
        with mock.patch.object(
            deploy_pipeline_executors, "_dispatch_github_actions_workflow",
            return_value=(0, ""),
        ) as workflow:
            rc, diag = _dispatch(
                _stage("github-actions-workflow"), project="platform",
                product_repo_path="/product", image_tag="abc123", member_items=[],
            )
        assert (rc, diag) == (0, "")
        kwargs = workflow.call_args.kwargs
        assert kwargs["project"] == "platform"
        assert kwargs["project_repo_path"] == "/repo"
        assert kwargs["product_repo_path"] == "/product"
        assert kwargs["image_tag"] == "abc123"

    def test_ephemeral_deploy_receives_branch_repo_and_label(self):
        with mock.patch(
            "yoke_core.domain.deploy_ephemeral.exec_ephemeral_deploy",
            return_value=0,
        ) as deploy, mock.patch.object(
            deploy_pipeline_executors, "_item_label", return_value="YOK-1",
        ):
            rc, diag = _dispatch(
                _stage("ephemeral-deploy"), target_env="ephemeral",
            )
        assert (rc, diag) == (0, "")
        deploy.assert_called_once_with(
            "yoke", branch="b", repo_path="/repo", image_tag="",
            item_label="YOK-1",
        )

    def test_ephemeral_deploy_config_branch_backstops_itemless_runs(self):
        with mock.patch(
            "yoke_core.domain.deploy_ephemeral.exec_ephemeral_deploy",
            return_value=0,
        ) as deploy, mock.patch.object(
            deploy_pipeline_executors, "_item_label", return_value="",
        ):
            rc, _diag = _dispatch(
                _stage("ephemeral-deploy", branch="cfg-branch"),
                branch="", first_item="", member_items=[],
                target_env="ephemeral",
            )
        assert rc == 0
        deploy.assert_called_once_with(
            "yoke", branch="cfg-branch", repo_path="/repo", image_tag="",
            item_label="",
        )

    def test_health_check_explicit_url_skips_env_resolution(self):
        with mock.patch.object(
            deploy_pipeline_executors._executors,
            "exec_health_check",
            return_value=0,
        ) as health, mock.patch.object(
            deploy_pipeline_executors,
            "verify_deployed_cli_manifest",
        ) as manifest:
            rc, _ = _dispatch(_stage("health-check", url="https://x/health"))
        assert rc == 0
        health.assert_called_once_with("https://x/health")
        manifest.assert_not_called()

    def test_health_check_resolves_env_url_with_request_id_and_build(self):
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
            deploy_pipeline_executors._executors,
            "exec_health_check",
            return_value=0,
        ) as health, mock.patch.object(
            deploy_pipeline_executors,
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

    def test_yoke_health_check_fails_on_manifest_drift(self):
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
            deploy_pipeline_executors._executors,
            "exec_health_check",
            return_value=0,
        ), mock.patch.object(
            deploy_pipeline_executors,
            "verify_deployed_cli_manifest",
            return_value=_manifest_gate(False),
        ):
            rc, _ = _dispatch(_stage("health-check"))
        assert rc == 1

    def test_health_check_without_repo_path_skips_build_assertion(self):
        fake_env = mock.Mock()
        fake_env.api_health_url = "https://api.example.com/v1/health"
        fake_env.git_branch = "main"
        fake_env.deploy_namespace = "buzz"
        with mock.patch(
            "yoke_core.domain.deploy_environment_settings."
            "resolve_deploy_environment",
            return_value=fake_env,
        ), mock.patch.object(
            deploy_pipeline_executors._executors,
            "exec_health_check",
            return_value=0,
        ) as health, mock.patch.object(
            deploy_pipeline_executors,
            "verify_deployed_cli_manifest",
            return_value=_manifest_gate(),
        ) as manifest:
            rc, _ = _dispatch(_stage("health-check"), project_repo_path="")
        assert rc == 0
        assert health.call_args.kwargs["expected_build"] == ""
        manifest.assert_not_called()

    def test_health_check_uses_pipeline_image_tag_without_repo_path(self):
        fake_env = mock.Mock()
        fake_env.api_health_url = "https://api.example.com/v1/health"
        fake_env.git_branch = "stage"
        with mock.patch(
            "yoke_core.domain.deploy_environment_settings."
            "resolve_deploy_environment",
            return_value=fake_env,
        ), mock.patch.object(
            deploy_pipeline_executors._executors,
            "exec_health_check",
            return_value=0,
        ) as health, mock.patch.object(
            deploy_pipeline_executors,
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

    def test_health_check_unresolvable_tag_skips_build_assertion(self):
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
            deploy_pipeline_executors._executors,
            "exec_health_check",
            return_value=0,
        ) as health, mock.patch.object(
            deploy_pipeline_executors,
            "verify_deployed_cli_manifest",
            return_value=_manifest_gate(),
        ):
            rc, _ = _dispatch(_stage("health-check"))
        assert rc == 0
        assert health.call_args.kwargs["expected_build"] == ""

    def test_health_check_env_resolved_fails_when_executor_reports_not_ready(self):
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
            deploy_pipeline_executors._executors,
            "exec_health_check",
            return_value=1,
        ), mock.patch.object(
            deploy_pipeline_executors,
            "verify_deployed_cli_manifest",
        ) as manifest:
            rc, _ = _dispatch(_stage("health-check"))
        assert rc == 1
        manifest.assert_not_called()

    def test_health_check_without_url_or_target_env_fails(self):
        rc, _ = _dispatch(_stage("health-check"), target_env="")
        assert rc == 1

    def test_unknown_executor_fails_loudly(self):
        rc, _ = _dispatch(_stage("not-a-real-executor"))
        assert rc == 1
