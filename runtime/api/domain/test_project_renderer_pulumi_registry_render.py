"""Registry-only artifact selection for the Pulumi project renderer."""

from __future__ import annotations

import pytest

from yoke_core.domain import project_renderer_pulumi
from runtime.api.domain.test_project_renderer_pulumi import (
    _stub_renderer_settings,
)


@pytest.fixture
def registry_tree(tmp_path):
    root = tmp_path / "repo"
    infra = root / "infra"
    infra.mkdir(parents=True)
    (infra / "Pulumi.yaml").write_text("name: webapp-infra\nruntime:\n  name: python\n")
    (infra / "Pulumi.stack.yaml.tmpl").write_text(
        "config:\n  webapp-infra:project_name: {{project_name}}\n"
    )
    (infra / "Pulumi.registry-stack.yaml.tmpl").write_text(
        "config:\n  aws:region: {{aws_region}}\n"
        '  webapp-infra:aws_account_id: "{{aws_account_id}}"\n'
        "  webapp-infra:project_name: {{project_name}}\n"
        "  webapp-infra:repository_name: {{repository_name}}\n"
    )
    program_files = {
        "__main__.py": "# pulumi entrypoint\n",
        "webapp_infra_stack.py": "# infra stack\n",
        "webapp_vps_stack.py": "# vps stack\n",
        "webapp_github_repository_provider.py": "# repository provider\n",
        "webapp_registry_stack.py": "# registry stack\n",
        "webapp_registry_ci_metadata_policy.py": "# registry metadata policy\n",
        "webapp_registry_ci_policy.py": "# cloudfront:ListDistributions\n",
        "webapp_registry_github_variables.py": "# registry GitHub variables\n",
        "requirements.txt": "pulumi>=3.0.0\n",
    }
    for name, content in program_files.items():
        (infra / name).write_text(content)
    project_root = root / "projects" / "yoke"
    project_root.mkdir(parents=True)
    return root, project_root


_VALUES = {
    "aws_region": "us-east-1",
    "aws_account_id": "123456789012",
    "project_name": "yoke",
}


def _render_registry(registry_tree, monkeypatch, **settings):
    _stub_renderer_settings(
        monkeypatch,
        "yoke",
        {"projectName": "yoke", "stacks": ["registry"], **settings},
    )
    root, project_root = registry_tree
    project_renderer_pulumi.render_pulumi_artifacts(
        "yoke",
        dict(_VALUES),
        root,
        project_root,
        write=True,
    )
    return project_root / "infra"


def test_renders_only_registry_files(registry_tree, monkeypatch):
    infra = _render_registry(registry_tree, monkeypatch)

    assert {path.name for path in infra.iterdir()} == {
        "Pulumi.yaml",
        "Pulumi.yoke-registry.yaml",
        "__main__.py",
        "webapp_github_repository_provider.py",
        "webapp_registry_ci_metadata_policy.py",
        "webapp_registry_ci_policy.py",
        "webapp_registry_github_variables.py",
        "webapp_registry_stack.py",
        "requirements.txt",
    }
    assert (infra / "webapp_registry_ci_policy.py").read_text() == (
        "# cloudfront:ListDistributions\n"
    )


def test_registry_config_defaults_repository_name(registry_tree, monkeypatch):
    infra = _render_registry(registry_tree, monkeypatch)

    registry_yaml = (infra / "Pulumi.yoke-registry.yaml").read_text()
    assert "repository_name: yoke-core" in registry_yaml
    assert "aws:region: us-east-1" in registry_yaml
    assert "{{" not in registry_yaml


def test_registry_config_honors_repository_override(registry_tree, monkeypatch):
    infra = _render_registry(
        registry_tree,
        monkeypatch,
        containerRepositoryName="yoke-images",
    )

    registry_yaml = (infra / "Pulumi.yoke-registry.yaml").read_text()
    assert "repository_name: yoke-images" in registry_yaml
