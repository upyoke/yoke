"""Stack-scoped Pulumi config projection tests."""

from __future__ import annotations

import json
from dataclasses import replace
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_core.domain.project_renderer_pulumi_stack_config import (
    PulumiStackConfigError,
    build_pulumi_stack_config,
)
from yoke_core.domain.project_renderer_pulumi_scoped import (
    render_scoped_pulumi_config,
)
from yoke_core.domain.pack_pulumi_sources import pulumi_generator_source
from yoke_core.tools.pulumi_exec_init import execute_pulumi_stack_init
from yoke_core.domain.project_renderer_settings import ProjectRendererSettings
from runtime.api.domain.pulumi_stack_config_test_support import (
    acme_environment as _environment,
    acme_settings as _settings,
    stub_acme_settings as _stub_settings,
)
from runtime.api.tools.pulumi_exec_support_test_support import (
    _Child,
    _install_pulumi_project_files,
)


def test_stack_config_projects_only_selected_environment(monkeypatch):
    settings = _settings()
    _stub_settings(monkeypatch, settings)

    payload = build_pulumi_stack_config(object(), "acme", "acme-stage")
    encoded = json.dumps(payload, sort_keys=True)
    assert payload["config_schema"] == 2
    assert payload["stack_kind"] == "environment"
    assert payload["render_values"]["origin_host"] == "origin.stage.acme.test"
    assert payload["render_values"]["origin_vps_stack_name"] == "acme-stage-vps"
    assert payload["render_values"]["origin_vps_elastic_ip_output"] == (
        "vpsElasticIpAddress"
    )
    assert payload["render_values"]["origin_vps_security_group_output"] == (
        "vpsSecurityGroupId"
    )
    assert "vps_ssh_key_name" not in payload["render_values"]
    assert payload["operator_state"] == {
        "secrets_provider": "awskms://alias/acme-stage",
        "encrypted_key": "encrypted-stage",
    }
    assert "origin.prod.acme.test" not in encoded
    assert "site_settings" not in payload
    assert "environments" not in payload
    assert "capabilities" not in payload
    assert payload["authority"]["github_project"] == "platform"
    assert payload["authority"]["github_permissions"] == {
        "metadata": "read",
        "actions_variables": "write",
    }


def test_variable_stack_projects_hosted_repository_provider_intent(monkeypatch):
    from yoke_core.domain import project_renderer_pulumi_stack_config as module

    settings = _settings()
    settings.capabilities["github-actions-runner-fleet"] = {}
    _stub_settings(monkeypatch, settings)
    seen = {}

    def provider_intent(selected_settings, *, expected_repo):
        seen.update(
            {
                "settings": selected_settings,
                "expected_repo": expected_repo,
            }
        )
        return "digest-bound-provider-intent"

    monkeypatch.setattr(
        module,
        "repository_provider_intent_from_settings",
        provider_intent,
    )

    payload = build_pulumi_stack_config(object(), "acme", "acme-stage")

    assert payload["authority"]["hosted_repository_token_intent"] == (
        "digest-bound-provider-intent"
    )
    assert seen == {
        "settings": settings,
        "expected_repo": "acme/app",
    }


def test_selected_environment_ignores_unrelated_incomplete_vps(monkeypatch):
    settings = _settings()
    settings.primary_environment.settings["servers"] = {}
    _stub_settings(monkeypatch, settings)

    payload = build_pulumi_stack_config(object(), "acme", "acme-stage")

    assert payload["stack_kind"] == "environment"
    assert payload["render_values"]["environment"] == "stage"


def test_selected_vps_still_requires_its_server_inputs(monkeypatch):
    settings = _settings()
    settings.environments[1].settings["servers"] = {}
    _stub_settings(monkeypatch, settings)

    with pytest.raises(ValueError, match="servers.instance_type"):
        build_pulumi_stack_config(object(), "acme", "acme-stage-vps")


def test_stack_config_projects_component_type_aliases(monkeypatch):
    settings = _settings()
    aliases = {
        "infra": ["legacy:infra:EdgeStack"],
        "vps": ["legacy:infra:HostStack"],
    }
    settings.capabilities["pulumi-state"]["component_type_aliases"] = aliases
    _stub_settings(monkeypatch, settings)

    payload = build_pulumi_stack_config(object(), "acme", "acme-stage-vps")

    assert (
        json.loads(payload["render_values"]["component_type_aliases_json"]) == aliases
    )


@pytest.mark.parametrize(
    ("stack", "instance_type", "root_volume_gb", "key_name", "encrypted_key"),
    [
        (
            "acme-prod-vps",
            "t4g.small",
            "40",
            "acme-prod",
            "encrypted-prod-vps",
        ),
        (
            "acme-stage-vps",
            "t4g.micro",
            "20",
            "acme-stage",
            "encrypted-stage-vps",
        ),
    ],
)
def test_stack_config_projects_environment_declared_standalone_vps(
    monkeypatch,
    tmp_path,
    stack,
    instance_type,
    root_volume_gb,
    key_name,
    encrypted_key,
):
    _stub_settings(monkeypatch, _settings())

    payload = build_pulumi_stack_config(object(), "acme", stack)

    assert payload["stack_kind"] == "vps"
    assert payload["render_values"]["vps_instance_type"] == instance_type
    assert payload["render_values"]["vps_root_volume_gb"] == root_volume_gb
    assert payload["render_values"]["vps_ssh_key_name"] == key_name
    assert payload["render_values"]["vps_iam_instance_profile_name"] == (
        f"{key_name}-host"
    )
    assert payload["operator_state"]["encrypted_key"] == encrypted_key
    assert "environments" not in payload
    assert "site_settings" not in payload
    stack_path = render_scoped_pulumi_config(
        payload,
        project_root=_install_pulumi_project_files(tmp_path),
        output_dir=tmp_path / stack,
    )
    rendered = stack_path.read_text()
    assert f"webapp-infra:vps_instance_type: {instance_type}" in rendered
    assert f'webapp-infra:vps_root_volume_gb: "{root_volume_gb}"' in rendered
    assert f"webapp-infra:vps_ssh_key_name: {key_name}" in rendered
    assert (stack_path.parent / "webapp_component_aliases.py").is_file()


def test_stack_config_rejects_unknown_and_missing_vps_operator_state(monkeypatch):
    settings = _settings()
    _stub_settings(monkeypatch, settings)
    with pytest.raises(ValueError, match="is not declared"):
        build_pulumi_stack_config(object(), "acme", "acme-unknown-vps")

    del settings.capabilities["pulumi-state"]["stack_state"]["acme-stage-vps"]
    with pytest.raises(PulumiStackConfigError, match="operator state is missing"):
        build_pulumi_stack_config(object(), "acme", "acme-stage-vps")


def test_stack_config_separates_environment_operator_state(monkeypatch):
    prod = _environment("prod")
    stage = _environment("stage")
    settings = ProjectRendererSettings(
        project="acme",
        deploy_namespace="acme",
        display_name="Acme",
        site_id="acme-site",
        site_settings={"domains": [{"domain_name": "acme.test"}]},
        primary_environment=prod,
        environments=(prod, stage),
        capabilities={
            "aws-admin": {"region": "us-east-1"},
            "pulumi-state": {"state_bucket": "acme-state", "stacks": ["infra"]},
        },
    )
    from yoke_core.domain import project_renderer_pulumi_stack_config as module

    monkeypatch.setattr(
        module,
        "resolve_project",
        lambda conn, project, required=False: SimpleNamespace(id=7, slug="acme"),
    )
    monkeypatch.setattr(
        module, "_load_project_renderer_settings", lambda conn, project: settings
    )
    monkeypatch.setattr(module, "_github_binding_for_repo", lambda *args: ("", {}))
    stage_payload = build_pulumi_stack_config(object(), "acme", "acme-stage")
    prod_payload = build_pulumi_stack_config(object(), "acme", "acme-prod")
    assert stage_payload["operator_state"]["encrypted_key"] == "encrypted-stage"
    assert prod_payload["operator_state"]["encrypted_key"] == ("encrypted-prod")


def _box_settings(**server_extra):
    """Acme plus one environment that declares only an extra box stack."""
    settings = _settings()
    box = _environment("box1")
    box.settings.clear()
    box.settings.update({
        "pulumi": {"origin_vps_stack_name": "acme-box1-vps"},
        "servers": [{
            "instance_type": "t4g.small",
            "root_volume_gb": 30,
            "aws_key_pair_name": "acme-box1",
            **server_extra,
        }],
    })
    return replace(settings, environments=(*settings.environments, box))


def test_box_ingress_and_zone_settings_reach_rendered_config(
    monkeypatch, tmp_path
):
    settings = _box_settings(public_ingress=False, availability_zone="us-east-1b")
    settings.capabilities["pulumi-state"]["stack_state"]["acme-box1-vps"] = {
        "secrets_provider": "awskms://alias/acme-box1-vps",
        "encrypted_key": "encrypted-box1-vps",
    }
    _stub_settings(monkeypatch, settings)

    payload = build_pulumi_stack_config(object(), "acme", "acme-box1-vps")

    assert payload["stack_kind"] == "vps"
    assert payload["render_values"]["vps_public_ingress"] == "false"
    assert payload["render_values"]["vps_availability_zone"] == "us-east-1b"
    project_root = _install_pulumi_project_files(tmp_path)
    template = pulumi_generator_source(project_root, "Pulumi.stack.yaml.tmpl")
    template.write_text(
        template.read_text()
        + '  webapp-infra:vps_public_ingress: "{{vps_public_ingress}}"\n'
        + '  webapp-infra:vps_availability_zone: "{{vps_availability_zone}}"\n'
    )
    rendered = render_scoped_pulumi_config(
        payload, project_root=project_root, output_dir=tmp_path / "box1"
    ).read_text()
    assert 'webapp-infra:vps_public_ingress: "false"' in rendered
    assert 'webapp-infra:vps_availability_zone: "us-east-1b"' in rendered


def test_absent_box_settings_default_open_ingress_and_render_unchanged(
    monkeypatch, tmp_path
):
    _stub_settings(monkeypatch, _settings())

    payload = build_pulumi_stack_config(object(), "acme", "acme-stage-vps")

    assert payload["render_values"]["vps_public_ingress"] == "true"
    assert payload["render_values"]["vps_availability_zone"] == ""
    rendered = render_scoped_pulumi_config(
        payload,
        project_root=_install_pulumi_project_files(tmp_path),
        output_dir=tmp_path / "stage",
    ).read_text()
    assert "vps_public_ingress" not in rendered
    assert "vps_availability_zone" not in rendered


def test_non_boolean_public_ingress_refuses_with_recipe(monkeypatch):
    _stub_settings(monkeypatch, _box_settings(public_ingress="no"))

    with pytest.raises(ValueError, match=r"--set servers\.0\.public_ingress="):
        build_pulumi_stack_config(object(), "acme", "acme-box1-vps")


def test_init_accepts_environment_declared_box_stack(tmp_path):
    provider = "awskms://alias/acme-pulumi-state?region=us-east-1"
    calls, imports = [], []

    def child_factory(command, **kwargs):
        stack_path = Path(kwargs["cwd"]) / "Pulumi.acme-box1-vps.yaml"
        stack_path.write_text(
            f"secretsprovider: {provider}\nencryptedkey: box-key\n"
            + stack_path.read_text()
        )
        calls.append(command)
        return _Child(b"initialized\n")

    rc = execute_pulumi_stack_init(
        "acme",
        "acme-box1-vps",
        ["init", "--secrets-provider", provider],
        project_root=_install_pulumi_project_files(tmp_path),
        settings_loader=lambda project: _box_settings(),
        state_importer=lambda **kw: imports.append(kw) or {"receipt_digest": "d"},
        aws_env_loader=lambda *args, **kwargs: {},
        child_factory=child_factory,
        out=StringIO(),
        err=StringIO(),
    )

    assert rc == 0
    assert calls[0][:4] == ["pulumi", "stack", "init", "acme-box1-vps"]
    assert imports[0]["stack_name"] == "acme-box1-vps"
