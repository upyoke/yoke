"""The environment stack owns the complete distribution variable contract."""

from __future__ import annotations

import types

from runtime.api.domain.test_webapp_registry_stack import (
    _Recorder,
    _load_template_module,
    _make_resource_class,
)


def _load_variables(monkeypatch):
    recorder = _Recorder()
    pulumi_github = types.ModuleType("pulumi_github")
    pulumi_github.ActionsVariable = _make_resource_class(
        recorder, "github:index/actionsVariable:ActionsVariable"
    )
    provider = types.ModuleType("webapp_github_repository_provider")
    provider.create_repository_provider = lambda *args, **kwargs: "provider"
    module = _load_template_module(
        monkeypatch,
        recorder,
        "webapp_distribution_github_variables.py",
        extra_modules={
            "pulumi_github": pulumi_github,
            "webapp_github_repository_provider": provider,
        },
    )
    return recorder, module


def test_environment_owns_every_distribution_publish_variable(monkeypatch):
    recorder, module = _load_variables(monkeypatch)

    variables = module.create_distribution_variables(
        variable_namespace="yoke",
        environment="stage",
        github_repo="upyoke/platform",
        github_api_url="https://api.github.com",
        base_url="https://api.stage.upyoke.com",
        bucket="upyoke-distribution-stage",
        cloudfront_id="E1849QD64JHXVC",
        origin_id="yoke-stage-distribution-static",
        child_opts=types.SimpleNamespace(),
    )

    assert variables == tuple(recorder.resources)
    assert [variable.kwargs["variable_name"] for variable in variables] == [
        "YOKE_STAGE_DISTRIBUTION_BASE_URL",
        "YOKE_STAGE_DISTRIBUTION_BUCKET",
        "YOKE_STAGE_DISTRIBUTION_CLOUDFRONT_ID",
        "YOKE_STAGE_DISTRIBUTION_ORIGIN_ID",
    ]
    assert [variable.kwargs["value"] for variable in variables] == [
        "https://api.stage.upyoke.com",
        "upyoke-distribution-stage",
        "E1849QD64JHXVC",
        "yoke-stage-distribution-static",
    ]
    assert all(variable.kwargs["repository"] == "platform" for variable in variables)
