"""A configured identity path without a url refuses before dispatch."""

from __future__ import annotations

from runtime.api.domain.test_deploy_pipeline_stage_receipt import (
    _dispatch_with,
    _qa_stage,
    _stage,
)


def test_configured_identity_path_without_url_refuses_before_dispatch() -> None:
    stage = _stage("deploy-stage", "github-actions-workflow")
    stages = [stage, _qa_stage("deploy-stage")]
    result, allocate, complete, _latest, dispatch = _dispatch_with(
        stage,
        stages,
        dispatch_return=(0, "workflow ok"),
        target_identity={
            "identity_path": "/api/orgs/upyoke/v1/health",
            "environment_urls": {},
        },
    )
    rc, diag = result
    assert rc == 1
    assert "no registered url" in diag
    assert (
        "yoke projects environment update --project yoke "
        "--environment stage --url https://<origin>"
    ) in diag
    dispatch.assert_not_called()
    allocate.assert_not_called()
    complete.assert_not_called()
