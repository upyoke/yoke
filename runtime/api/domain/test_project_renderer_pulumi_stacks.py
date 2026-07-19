"""Tests for the stack-set-aware renderer path in project_renderer_pulumi.py.

Split from ``test_project_renderer_pulumi.py`` (which stays under the 350-line
file budget). Covers ``gather_pulumi_stacks`` and the domain-only render that a
project declaring ``stacks=["domain"]`` produces — no EC2/CloudFront surface.
"""

from __future__ import annotations

import ast

import pytest

from yoke_core.domain import project_renderer_pulumi
from runtime.api.domain.test_project_renderer_pulumi import (
    _make_project_root,
    _stub_renderer_settings,
)
from runtime.api.domain.webapp_pulumi_test_support import _pack_program_source


class TestGatherPulumiStacks:
    def test_capability_stack_set_overrides_site_declaration(
        self, tmp_path, monkeypatch,
    ):
        settings = _stub_renderer_settings(
            monkeypatch,
            "platform",
            {"projectName": "platform", "stacks": ["infra", "vps"]},
        )
        capabilities = dict(settings.capabilities)
        capabilities["pulumi-state"] = {
            "stacks": ["registry", "runner-fleet"],
        }
        capability_settings = type(settings)(
            project=settings.project,
            deploy_namespace="yoke",
            display_name=settings.display_name,
            site_id=settings.site_id,
            site_settings=settings.site_settings,
            primary_environment=settings.primary_environment,
            environments=settings.environments,
            capabilities=capabilities,
        )
        root = _make_project_root(tmp_path, "platform")

        assert project_renderer_pulumi.gather_pulumi_stacks(
            "platform", root, capability_settings,
        ) == ["registry", "runner-fleet"]

    def test_defaults_to_infra_vps_when_absent(self, tmp_path, monkeypatch):
        _stub_renderer_settings(monkeypatch, "externalwebapp", {"projectName": "externalwebapp"})
        root = _make_project_root(tmp_path, "externalwebapp")
        assert project_renderer_pulumi.gather_pulumi_stacks("externalwebapp", root) == [
            "infra",
            "vps",
        ]

    def test_reads_explicit_domain_only(self, tmp_path, monkeypatch):
        _stub_renderer_settings(
            monkeypatch,
            "yoke",
            {"projectName": "yoke", "stacks": ["domain"]},
        )
        root = _make_project_root(tmp_path, "yoke")
        assert project_renderer_pulumi.gather_pulumi_stacks("yoke", root) == [
            "domain",
        ]

    def test_reads_explicit_infra_vps(self, tmp_path, monkeypatch):
        _stub_renderer_settings(
            monkeypatch,
            "externalwebapp",
            {"projectName": "externalwebapp", "stacks": ["infra", "vps"]},
        )
        root = _make_project_root(tmp_path, "externalwebapp")
        assert project_renderer_pulumi.gather_pulumi_stacks("externalwebapp", root) == [
            "infra",
            "vps",
        ]

    def test_reads_explicit_registry(self, tmp_path, monkeypatch):
        _stub_renderer_settings(
            monkeypatch,
            "yoke",
            {"projectName": "yoke", "stacks": ["registry"]},
        )
        root = _make_project_root(tmp_path, "yoke")
        assert project_renderer_pulumi.gather_pulumi_stacks("yoke", root) == [
            "registry",
        ]

    def test_reads_yoke_stack_set(self, tmp_path, monkeypatch):
        _stub_renderer_settings(
            monkeypatch,
            "yoke",
            {
                "projectName": "yoke",
                "stacks": ["domain", "registry", "infra", "runner-fleet"],
            },
        )
        root = _make_project_root(tmp_path, "yoke")
        assert project_renderer_pulumi.gather_pulumi_stacks("yoke", root) == [
            "domain",
            "registry",
            "infra",
            "runner-fleet",
        ]

    def test_rejects_unknown_stack_type(self, tmp_path, monkeypatch):
        _stub_renderer_settings(
            monkeypatch,
            "yoke",
            {"projectName": "yoke", "stacks": ["doamin"]},
        )
        root = _make_project_root(tmp_path, "yoke")
        with pytest.raises(ValueError, match="Unknown Pulumi stack type"):
            project_renderer_pulumi.gather_pulumi_stacks("yoke", root)


class TestRenderDomainOnly:
    """A project declaring stacks=["domain"] renders ONLY domain artifacts."""

    @pytest.fixture
    def domain_tree(self, tmp_path, monkeypatch):
        root = tmp_path / "repo"
        infra = root / "infra"
        infra.mkdir(parents=True)
        (infra / "Pulumi.yaml").write_text(
            "name: webapp-infra\nruntime:\n  name: python\n"
        )
        # Both stack-config templates present, plus all program modules — the
        # renderer must select only the domain ones for a domain-only project.
        (infra / "Pulumi.stack.yaml.tmpl").write_text(
            "config:\n  webapp-infra:project_name: {{project_name}}\n"
        )
        (infra / "Pulumi.domain-stack.yaml.tmpl").write_text(
            "config:\n  aws:region: {{aws_region}}\n"
            "  webapp-infra:project_name: {{project_name}}\n"
            "  webapp-infra:domain_name: {{domain_name}}\n"
            "  webapp-infra:import_zone_id: {{import_zone_id}}\n"
            '  webapp-infra:manage_registration: "{{manage_registration}}"\n'
            "  webapp-infra:domain_txt_records: '{{domain_txt_records_json}}'\n"
            "  webapp-infra:domain_mx_records: '{{domain_mx_records_json}}'\n"
        )
        (infra / "__main__.py").write_text("# pulumi entrypoint\n")
        (infra / "webapp_infra_stack.py").write_text("# infra stack\n")
        (infra / "webapp_vps_stack.py").write_text("# vps stack\n")
        (infra / "webapp_domain_stack.py").write_text("# domain stack\n")
        (infra / "webapp_dns_records.py").write_text("# dns helper\n")
        (infra / "requirements.txt").write_text("pulumi>=3.0.0\n")

        proj = root / "projects" / "yoke"
        proj.mkdir(parents=True)
        _stub_renderer_settings(
            monkeypatch,
            "yoke",
            {
                "projectName": "yoke",
                "stacks": ["domain"],
                "hostedZoneId": "ZADOPTME123",
                "txtRecords": [
                    {
                        "id": "googleWorkspaceVerification",
                        "name": "@",
                        "value": "google-site-verification=abc123",
                        "ttl": 300,
                    }
                ],
                "mxRecords": [
                    {
                        "id": "googleWorkspaceGmail",
                        "name": "@",
                        "priority": 1,
                        "value": "SMTP.GOOGLE.COM",
                        "ttl": 300,
                    }
                ],
            },
        )
        return root, proj

    def test_renders_only_domain_files(self, domain_tree):
        root, proj = domain_tree
        values = {
            "aws_region": "us-east-1",
            "aws_account_id": "123456789012",
            "project_name": "yoke",
            "domain_name": "example.com",
        }
        project_renderer_pulumi.render_pulumi_artifacts(
            "yoke",
            values,
            root,
            proj,
            write=True,
        )
        names = {p.name for p in (proj / "infra").iterdir()}
        # Domain-only output: shared files + domain stack + domain config YAML.
        assert names == {
            "Pulumi.yaml",
            "Pulumi.yoke-domain.yaml",
            "__main__.py",
            "webapp_domain_stack.py",
            "webapp_dns_records.py",
            "requirements.txt",
        }
        # No infra/vps surface leaks into a domain-only project.
        assert "webapp_infra_stack.py" not in names
        assert "webapp_vps_stack.py" not in names
        assert "Pulumi.yoke-infra.yaml" not in names
        assert "Pulumi.yoke-vps.yaml" not in names

    def test_domain_config_omits_infra_keys(self, domain_tree):
        root, proj = domain_tree
        values = {
            "aws_region": "us-east-1",
            "aws_account_id": "123456789012",
            "project_name": "yoke",
            "domain_name": "example.com",
        }
        project_renderer_pulumi.render_pulumi_artifacts(
            "yoke",
            values,
            root,
            proj,
            write=True,
        )
        domain_yaml = (proj / "infra" / "Pulumi.yoke-domain.yaml").read_text()
        # Domain config carries only domain keys, never the infra/vps
        # config keys, and substitutes manage_registration (default false).
        assert "example.com" in domain_yaml
        assert 'manage_registration: "false"' in domain_yaml
        assert (
            'domain_txt_records: \'[{"id":"googleWorkspaceVerification"' in domain_yaml
        )
        assert "google-site-verification=abc123" in domain_yaml
        assert 'domain_mx_records: \'[{"id":"googleWorkspaceGmail"' in domain_yaml
        assert "SMTP.GOOGLE.COM" in domain_yaml
        # hosted_zone_id from DB settings is injected as import_zone_id so a
        # future `pulumi up` adopts the registrar-auto-created zone instead of
        # duplicating it.
        assert "import_zone_id: ZADOPTME123" in domain_yaml
        assert "hosted_zone_id" not in domain_yaml
        assert "certificate_arn" not in domain_yaml
        assert "origin_id" not in domain_yaml
        assert "vps_instance_type" not in domain_yaml
        assert "{{" not in domain_yaml

    def test_infra_config_skips_txt_records_when_domain_stack_owns_them(
        self,
        tmp_path,
        monkeypatch,
    ):
        root = tmp_path / "repo"
        infra = root / "infra"
        infra.mkdir(parents=True)
        (infra / "Pulumi.yaml").write_text(
            "name: webapp-infra\nruntime:\n  name: python\n"
        )
        (infra / "Pulumi.stack.yaml.tmpl").write_text(
            "config:\n"
            "  webapp-infra:project_name: {{project_name}}\n"
            "  webapp-infra:domain_txt_records: '{{domain_txt_records_json}}'\n"
            "  webapp-infra:domain_mx_records: '{{domain_mx_records_json}}'\n"
        )
        (infra / "Pulumi.domain-stack.yaml.tmpl").write_text(
            "config:\n"
            "  webapp-infra:project_name: {{project_name}}\n"
            "  webapp-infra:domain_name: {{domain_name}}\n"
            "  webapp-infra:import_zone_id: {{import_zone_id}}\n"
            '  webapp-infra:manage_registration: "{{manage_registration}}"\n'
            "  webapp-infra:domain_txt_records: '{{domain_txt_records_json}}'\n"
            "  webapp-infra:domain_mx_records: '{{domain_mx_records_json}}'\n"
        )
        (infra / "__main__.py").write_text("# pulumi entrypoint\n")
        (infra / "webapp_infra_stack.py").write_text("# infra stack\n")
        (infra / "webapp_domain_stack.py").write_text("# domain stack\n")
        (infra / "webapp_dns_records.py").write_text("# dns helper\n")
        (infra / "requirements.txt").write_text("pulumi>=3.0.0\n")
        proj = root / "projects" / "yoke"
        proj.mkdir(parents=True)
        _stub_renderer_settings(
            monkeypatch,
            "yoke",
            {
                "projectName": "yoke",
                "stacks": ["domain", "infra"],
                "txtRecords": [{"name": "@", "value": "verification"}],
                "mxRecords": [{"name": "@", "priority": 1, "value": "SMTP.GOOGLE.COM"}],
            },
        )
        values = {
            "aws_region": "us-east-1",
            "project_name": "yoke",
            "domain_name": "example.com",
            "domain_txt_records_json": ('[{"name":"@","value":"verification"}]'),
            "domain_mx_records_json": (
                '[{"name":"@","priority":1,"value":"SMTP.GOOGLE.COM"}]'
            ),
        }

        project_renderer_pulumi.render_pulumi_artifacts(
            "yoke",
            values,
            root,
            proj,
            write=True,
        )

        domain_yaml = (proj / "infra" / "Pulumi.yoke-domain.yaml").read_text()
        infra_yaml = (proj / "infra" / "Pulumi.yoke-infra.yaml").read_text()
        assert "verification" in domain_yaml
        assert "SMTP.GOOGLE.COM" in domain_yaml
        assert "domain_txt_records: '[]'" in infra_yaml
        assert "domain_mx_records: '[]'" in infra_yaml


def test_pulumi_entrypoint_uses_branch_local_stack_imports():
    entrypoint = _pack_program_source("__main__.py")
    tree = ast.parse(entrypoint.read_text())
    top_level_imports = {
        node.module for node in tree.body if isinstance(node, ast.ImportFrom)
    }

    assert (
        not {
            "webapp_domain_stack",
            "webapp_infra_stack",
            "webapp_vps_stack",
        }
        & top_level_imports
    )


def test_domain_registration_nameservers_transform_pulumi_output():
    stack = _pack_program_source("webapp_domain_stack.py").read_text()

    assert "name_servers=self.hosted_zone.name_servers.apply(" in stack
    assert "for ns in self.hosted_zone.name_servers" not in stack
