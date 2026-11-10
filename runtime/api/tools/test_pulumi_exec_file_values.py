"""Yoke-owned values and stack-file merging for file-backed Pulumi stacks."""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import yaml

from yoke_core.domain.project_renderer_settings import RendererEnvironmentSettings
from yoke_core.domain.pulumi_file_stack_values import (
    FileStackValuesError,
    file_stack_authority,
    file_stack_yoke_values,
)
from yoke_core.tools.pulumi_exec_file_backed import (
    file_backed_stack_path,
    file_stack_github_access,
    merge_yoke_config,
)
from yoke_core.tools.pulumi_exec_types import PulumiExecError
from runtime.api.tools.pulumi_exec_support_test_support import _init_settings


_SOURCE = Path("Pulumi.s.yaml")
_VALUES = {"aws_region": "us-east-1", "deploy_namespace": "ns"}


def _merged_config(text: str) -> dict:
    return yaml.safe_load(merge_yoke_config(text, _VALUES, source=_SOURCE))["config"]


def test_block_merge_keeps_project_text_exactly():
    text = (
        "secretsprovider: awskms://alias/x?region=us-east-1\n"
        "encryptedkey: abc\n"
        "config:\n"
        "  # project sizing\n"
        "  app:enabled: yes\n"
        "  app:mode: '0755'\n"
    )
    merged = merge_yoke_config(text, _VALUES, source=_SOURCE)
    assert "  app:enabled: yes\n" in merged
    assert "  # project sizing\n" in merged
    assert "  app:mode: '0755'\n" in merged
    assert merged.startswith("secretsprovider: awskms://alias/x?region=us-east-1\n")
    config = yaml.safe_load(merged)["config"]
    assert config["yoke:aws_region"] == "us-east-1"
    assert config["yoke:deploy_namespace"] == "ns"


@pytest.mark.parametrize(
    "text",
    [
        "encryptedkey: abc\n",
        "encryptedkey: abc",
        "config: {}\n",
        "config: {app:size: small}\n",
        "config:\n",
        "config: ~\n",
        "",
    ],
)
def test_merge_handles_every_config_shape(text):
    config = _merged_config(text)
    assert config["yoke:aws_region"] == "us-east-1"
    assert config["yoke:deploy_namespace"] == "ns"
    if "app:size" in text:
        assert config["app:size"] == "small"


def test_merge_refuses_non_mapping_config():
    with pytest.raises(PulumiExecError, match="pulumi_stack_file_invalid"):
        merge_yoke_config("config: [1]\n", _VALUES, source=_SOURCE)


def _write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "Pulumi.s.yaml"
    path.write_text(body)
    return path


def test_github_access_defaults_to_metadata(tmp_path):
    assert file_stack_github_access(_write(tmp_path, "config:\n  a:b: c\n")) == "metadata"


@pytest.mark.parametrize("level", ["metadata", "variables", "runner_fleet"])
def test_github_access_follows_the_file(tmp_path, level):
    path = _write(tmp_path, f"config:\n  yoke:github_access: {level}\n")
    assert file_stack_github_access(path) == level


@pytest.mark.parametrize("value", ["admin", "true", "[metadata]"])
def test_unknown_github_access_refuses(tmp_path, value):
    path = _write(tmp_path, f"config:\n  yoke:github_access: {value}\n")
    with pytest.raises(PulumiExecError, match="pulumi_github_access_unknown"):
        file_stack_github_access(path)


def test_other_yoke_keys_in_the_file_refuse(tmp_path):
    path = _write(tmp_path, "config:\n  yoke:aws_account_id: '1'\n")
    with pytest.raises(PulumiExecError, match="pulumi_yoke_namespace_reserved"):
        file_stack_github_access(path)


@pytest.mark.parametrize("stack", ["../x", "a/b", "", ".hidden"])
def test_unsafe_stack_names_are_never_file_backed(tmp_path, stack):
    (tmp_path / "infra").mkdir()
    assert file_backed_stack_path(tmp_path, stack) is None


def test_values_are_yoke_owned_only_with_no_defaults():
    settings = _init_settings()
    values = file_stack_yoke_values(settings, "scratch", "metadata")
    assert values["aws_account_id"] == "657517041453"
    assert values["aws_region"] == "us-east-1"
    assert values["deploy_namespace"] == "externalwebapp"
    assert values["kms_key_alias"] == "alias/externalwebapp-pulumi-state"
    assert values["github_repo_slug"] == "beebauman/externalwebapp"
    assert "delivery_authority_json" in values
    assert values["component_type_aliases_json"] == "{}"
    project_specific = {
        "vps_instance_type", "vps_root_volume_gb", "domain_txt_records_json",
        "state_bucket", "manage_github_oidc_provider", "project_name",
    }
    assert not project_specific & values.keys()
    assert not any(key.startswith("runner_fleet_") for key in values)
    assert all(value for value in values.values())


def test_missing_account_is_omitted_not_defaulted():
    settings = _init_settings()
    settings.capabilities["aws-admin"].pop("account_id")
    values = file_stack_yoke_values(settings, "scratch", "metadata")
    assert "aws_account_id" not in values


def test_environment_facts_follow_the_matching_environment():
    settings = _init_settings()
    env = RendererEnvironmentSettings(
        id="1",
        name="production",
        settings={
            "pulumi": {"stack_name": "prod-box", "origin_vps_stack_name": "vps"},
            "hosts": {"api": "api.example.com", "origin": "o.example.com"},
            "database": {"name": "app", "min_capacity_acu": 2},
        },
    )
    settings = dataclasses.replace(settings, environments=(env,))
    values = file_stack_yoke_values(settings, "prod-box", "metadata")
    assert values["environment"] == "production"
    assert values["api_host"] == "api.example.com"
    assert values["origin_vps_stack_name"] == "vps"
    assert values["database_name"] == "app"
    assert "database_min_capacity_acu" not in values
    assert "environment" not in file_stack_yoke_values(settings, "other", "metadata")


@pytest.mark.parametrize(
    ("level", "permissions"),
    [
        ("metadata", {"metadata": "read"}),
        ("variables", {"metadata": "read", "actions_variables": "write"}),
    ],
)
def test_authority_grants_exactly_the_file_level(level, permissions):
    settings = _init_settings()
    values = file_stack_yoke_values(settings, "scratch", level)
    authority = file_stack_authority(settings, values, level)
    assert authority["github_permissions"] == permissions
    assert authority["github_project"] == "externalwebapp"
    assert authority["github_repo"] == "beebauman/externalwebapp"
    assert authority["backend_url"] == (
        "s3://externalwebapp-pulumi-state?region=us-east-1"
    )


def test_authority_refuses_unknown_level_and_missing_backend():
    settings = _init_settings()
    with pytest.raises(FileStackValuesError, match="pulumi_github_access_unknown"):
        file_stack_authority(settings, {}, "admin")
    settings.capabilities["pulumi-state"].pop("state_bucket")
    with pytest.raises(FileStackValuesError, match="pulumi_backend_authority_missing"):
        file_stack_authority(settings, {}, "metadata")
