"""Operator-state and stable-name authority for Pulumi stack instances."""

from __future__ import annotations

from yoke_core.domain import project_renderer_pulumi
from yoke_core.domain.project_renderer_pulumi_instances import (
    pulumi_stack_instances_from_settings,
)
from yoke_core.domain.project_renderer_settings import ProjectRendererSettings
from runtime.api.domain.test_project_renderer_pulumi_instances import (
    _environment_settings,
    _make_project_tree,
    _settings_with_environments,
    _stub_settings,
)


def test_preserves_operator_state_and_warns_on_config_divergence(
    tmp_path, monkeypatch, capsys,
):
    root, proj = _make_project_tree(tmp_path, "yoke")
    settings = _settings_with_environments(
        "yoke", ["infra"], [_environment_settings("yoke-prod", "prod")],
    )
    _stub_settings(monkeypatch, settings)
    values = {
        "aws_region": "us-east-1",
        "domain_name": "example.com",
        "project_name": "yoke",
    }
    project_renderer_pulumi.render_pulumi_artifacts(
        "yoke", values, root, proj, write=True,
    )
    stack_path = proj / "infra" / "Pulumi.yoke-prod.yaml"
    operator_state = (
        "secretsprovider: awskms://alias/yoke-pulumi-state?region=us-east-1\n"
        "encryptedkey: AAABAJxOPAQUE_OPERATOR_KEY==\n"
    )
    stack_path.write_text(
        operator_state + stack_path.read_text().replace('"0"', '"1"')
    )
    capsys.readouterr()

    project_renderer_pulumi.render_pulumi_artifacts(
        "yoke", values, root, proj, write=True,
    )
    text = stack_path.read_text()
    err = capsys.readouterr().err

    assert text.count("secretsprovider:") == 1
    assert text.count("encryptedkey:") == 1
    assert '"1"' not in text
    assert '"0"' in text
    assert "WARNING" in err
    assert "webapp-infra:database_min_capacity_acu" in err
    assert "DB-backed site/environment/capability settings" in err


def test_default_distribution_origin_id_uses_deploy_namespace_not_project():
    env = _environment_settings("yoke-stage", "stage")
    env.settings["distribution"] = {
        "bucket_name": "yoke-stage-artifacts",
        "base_url": "https://api.stage.example.com",
    }
    settings = ProjectRendererSettings(
        project="platform",
        deploy_namespace="yoke",
        display_name="Platform",
        site_id="yoke-api",
        site_settings={},
        primary_environment=env,
        environments=(env,),
        capabilities={},
    )

    instances = pulumi_stack_instances_from_settings(settings)

    assert instances[0].config["distribution_origin_id"] == (
        "yoke-stage-distribution-static"
    )
    assert instances[0].config["distribution_base_url"] == (
        "https://api.stage.example.com"
    )
