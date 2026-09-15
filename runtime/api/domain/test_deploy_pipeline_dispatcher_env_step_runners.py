"""Dispatcher tests for the env-aware step_runners (activate / core-deploy / health)."""

from __future__ import annotations

from unittest import mock

from yoke_core.domain import deploy_pipeline_step_runners


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


class TestEnvStepRunnerDispatch:
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
            deploy_pipeline_step_runners, "_dispatch_github_actions_workflow",
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
        ) as deploy:
            rc, diag = _dispatch(
                _stage("ephemeral-deploy"), environment_name="",
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
        ) as deploy:
            rc, _diag = _dispatch(
                _stage("ephemeral-deploy", branch="cfg-branch"),
                branch="", first_item="", member_items=[],
                first_item_label="",
                environment_name="",
            )
        assert rc == 0
        deploy.assert_called_once_with(
            "yoke", branch="cfg-branch", repo_path="/repo", image_tag="",
            item_label="",
        )

    def test_unknown_step_runner_fails_loudly(self):
        rc, _ = _dispatch(_stage("not-a-real-step_runner"))
        assert rc == 1
