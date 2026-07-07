"""Render-output tests for project_renderer_pulumi.py."""

from __future__ import annotations

import pytest

from yoke_core.domain import project_renderer_pulumi
from yoke_core.domain.project_renderer_pulumi_state import (
    _operator_state_lines_from_settings,
)
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)


def _settings_with_pulumi_state(
    project: str, stack_name: str, **pulumi_keys: str,
) -> ProjectRendererSettings:
    """Minimal settings snapshot: one env whose pulumi block names a stack."""
    env = RendererEnvironmentSettings(
        id=f"{project}-prod",
        name="prod",
        settings={"pulumi": {"stack_name": stack_name, **pulumi_keys}},
    )
    return ProjectRendererSettings(
        project=project,
        display_name=project.title(),
        site_id=f"{project}-site",
        site_settings={},
        primary_environment=env,
        environments=(env,),
        capabilities={},
    )


class TestRenderPulumiArtifacts:
    @pytest.fixture
    def infra_tree(self, tmp_path):
        """Build a project root with the seven infra template files."""
        root = tmp_path / "repo"
        infra = root / "templates" / "webapp" / "infra"
        infra.mkdir(parents=True)

        (infra / "Pulumi.yaml").write_text(
            "name: webapp-infra\nruntime:\n  name: python\n"
        )
        (infra / "Pulumi.stack.yaml.tmpl").write_text(
            "config:\n  aws:region: {{aws_region}}\n"
            "  webapp-infra:project_name: {{project_name}}\n"
        )
        (infra / "__main__.py").write_text("# pulumi entrypoint\n")
        (infra / "webapp_infra_stack.py").write_text("# infra stack\n")
        (infra / "webapp_vps_stack.py").write_text("# vps stack\n")
        (infra / "requirements.txt").write_text("pulumi>=3.0.0\n")

        proj = root / "projects" / "buzz"
        proj.mkdir(parents=True)
        return root, proj

    def test_writes_seven_files(self, infra_tree, monkeypatch):
        monkeypatch.setattr(
            project_renderer_pulumi,
            "gather_pulumi_stacks",
            lambda _project, _root, _settings=None: ["infra", "vps"],
        )
        monkeypatch.setattr(
            project_renderer_pulumi,
            "gather_pulumi_stack_instances",
            lambda _project, _root, _settings=None: [],
        )
        root, proj = infra_tree
        values = {
            "aws_region": "us-east-1",
            "project_name": "buzz",
            "pulumi_infra_stack_name": "buzz-infra",
            "pulumi_vps_stack_name": "buzz-vps",
        }
        project_renderer_pulumi.render_pulumi_artifacts(
            "buzz", values, root, proj, write=True,
        )
        infra_dst = proj / "infra"
        expected = {
            "Pulumi.yaml",
            "Pulumi.buzz-infra.yaml",
            "Pulumi.buzz-vps.yaml",
            "__main__.py",
            "webapp_infra_stack.py",
            "webapp_vps_stack.py",
            "requirements.txt",
        }
        assert {p.name for p in infra_dst.iterdir()} == expected

        infra_stack = (infra_dst / "Pulumi.buzz-infra.yaml").read_text()
        assert "us-east-1" in infra_stack
        assert "buzz" in infra_stack
        assert "{{" not in infra_stack

        vps_stack = (infra_dst / "Pulumi.buzz-vps.yaml").read_text()
        assert "us-east-1" in vps_stack
        assert "buzz" in vps_stack
        assert "{{" not in vps_stack

        src_main = (root / "templates/webapp/infra/__main__.py").read_text()
        dst_main = (infra_dst / "__main__.py").read_text()
        assert dst_main == src_main
        assert "AUTO-GENERATED" not in dst_main

        assert not (infra_dst / "buzz_infra_stack.py").exists()
        assert not (infra_dst / "buzz_vps_stack.py").exists()
        assert (infra_dst / "webapp_infra_stack.py").read_text() == "# infra stack\n"
        assert (infra_dst / "webapp_vps_stack.py").read_text() == "# vps stack\n"

    def test_preserves_operator_secrets_provider(self, infra_tree, monkeypatch):
        """Re-render after `pulumi stack init` must not strip secretsprovider."""
        monkeypatch.setattr(
            project_renderer_pulumi,
            "gather_pulumi_stacks",
            lambda _project, _root, _settings=None: ["infra", "vps"],
        )
        monkeypatch.setattr(
            project_renderer_pulumi,
            "gather_pulumi_stack_instances",
            lambda _project, _root, _settings=None: [],
        )
        root, proj = infra_tree
        values = {
            "aws_region": "us-east-1",
            "project_name": "buzz",
            "pulumi_infra_stack_name": "buzz-infra",
            "pulumi_vps_stack_name": "buzz-vps",
        }

        project_renderer_pulumi.render_pulumi_artifacts(
            "buzz", values, root, proj, write=True,
        )
        infra_stack_path = proj / "infra" / "Pulumi.buzz-infra.yaml"
        first_render = infra_stack_path.read_text()
        assert "secretsprovider:" not in first_render

        operator_state = (
            "secretsprovider: awskms://alias/buzz-pulumi-state?region=us-east-1\n"
            "encryptedkey: AAABAJxOPAQUE_OPERATOR_KEY_PAYLOAD==\n"
        )
        infra_stack_path.write_text(operator_state + first_render)

        project_renderer_pulumi.render_pulumi_artifacts(
            "buzz", values, root, proj, write=True,
        )
        re_rendered = infra_stack_path.read_text()
        assert "awskms://alias/buzz-pulumi-state?region=us-east-1" in re_rendered
        assert "encryptedkey: AAABAJxOPAQUE_OPERATOR_KEY_PAYLOAD==" in re_rendered
        assert "aws:region: us-east-1" in re_rendered
        assert "{{" not in re_rendered

        project_renderer_pulumi.render_pulumi_artifacts(
            "buzz", values, root, proj, write=True,
        )
        twice_rendered = infra_stack_path.read_text()
        assert twice_rendered.count("secretsprovider:") == 1
        assert twice_rendered.count("encryptedkey:") == 1


_PROVIDER = "awskms://alias/buzz-pulumi-state?region=us-east-1"
_KEY = "AAABAJxOPAQUE_OPERATOR_KEY_PAYLOAD=="


class TestOperatorStateLinesFromSettings:
    """Unit coverage for the durable settings-sourced fallback."""

    def test_matching_stack_renders_both_lines(self):
        settings = _settings_with_pulumi_state(
            "buzz", "buzz-prod",
            secrets_provider=_PROVIDER, encrypted_key=_KEY,
        )
        assert _operator_state_lines_from_settings(settings, "buzz-prod") == (
            f"secretsprovider: {_PROVIDER}\nencryptedkey: {_KEY}\n"
        )

    def test_non_matching_stack_renders_nothing(self):
        settings = _settings_with_pulumi_state(
            "buzz", "buzz-prod",
            secrets_provider=_PROVIDER, encrypted_key=_KEY,
        )
        assert _operator_state_lines_from_settings(settings, "buzz-infra") == ""

    def test_absent_keys_render_nothing(self):
        settings = _settings_with_pulumi_state("buzz", "buzz-prod")
        assert _operator_state_lines_from_settings(settings, "buzz-prod") == ""

    def test_single_present_key_renders_alone(self):
        settings = _settings_with_pulumi_state(
            "buzz", "buzz-prod", secrets_provider=_PROVIDER,
        )
        assert _operator_state_lines_from_settings(settings, "buzz-prod") == (
            f"secretsprovider: {_PROVIDER}\n"
        )


class TestFreshRenderSettingsFallback:
    """Fresh renders (per-run scratch dirs) source state lines from
    ``environments.settings.pulumi`` when no existing file carries them;
    existing-file lines always win over settings."""

    @pytest.fixture
    def infra_tree(self, tmp_path):
        root = tmp_path / "repo"
        infra = root / "templates" / "webapp" / "infra"
        infra.mkdir(parents=True)
        (infra / "Pulumi.yaml").write_text(
            "name: webapp-infra\nruntime:\n  name: python\n"
        )
        (infra / "Pulumi.stack.yaml.tmpl").write_text(
            "config:\n  aws:region: {{aws_region}}\n"
            "  webapp-infra:project_name: {{project_name}}\n"
        )
        (infra / "__main__.py").write_text("# pulumi entrypoint\n")
        (infra / "webapp_infra_stack.py").write_text("# infra stack\n")
        (infra / "requirements.txt").write_text("pulumi>=3.0.0\n")
        proj = root / "projects" / "buzz"
        proj.mkdir(parents=True)
        return root, proj

    def _stub(self, monkeypatch, settings) -> None:
        monkeypatch.setattr(
            project_renderer_pulumi,
            "load_project_renderer_settings",
            lambda _project: settings,
        )
        monkeypatch.setattr(
            project_renderer_pulumi,
            "gather_pulumi_stacks",
            lambda _project, _root, _settings=None: ["infra"],
        )
        monkeypatch.setattr(
            project_renderer_pulumi,
            "gather_pulumi_stack_instances",
            lambda _project, _root, _settings=None: [],
        )

    _VALUES = {
        "aws_region": "us-east-1",
        "project_name": "buzz",
        "pulumi_infra_stack_name": "buzz-infra",
    }

    def test_fresh_render_sources_state_lines_from_settings(
        self, infra_tree, monkeypatch,
    ):
        root, proj = infra_tree
        self._stub(monkeypatch, _settings_with_pulumi_state(
            "buzz", "buzz-infra",
            secrets_provider=_PROVIDER, encrypted_key=_KEY,
        ))
        project_renderer_pulumi.render_pulumi_artifacts(
            "buzz", dict(self._VALUES), root, proj, write=True,
        )
        rendered = (proj / "infra" / "Pulumi.buzz-infra.yaml").read_text()
        assert rendered.startswith(f"secretsprovider: {_PROVIDER}\n")
        assert f"encryptedkey: {_KEY}" in rendered
        assert "aws:region: us-east-1" in rendered
        assert "{{" not in rendered

    def test_fresh_render_without_settings_keys_is_unchanged(
        self, infra_tree, monkeypatch,
    ):
        root, proj = infra_tree
        self._stub(
            monkeypatch, _settings_with_pulumi_state("buzz", "buzz-infra"),
        )
        project_renderer_pulumi.render_pulumi_artifacts(
            "buzz", dict(self._VALUES), root, proj, write=True,
        )
        rendered = (proj / "infra" / "Pulumi.buzz-infra.yaml").read_text()
        assert "secretsprovider:" not in rendered
        assert "encryptedkey:" not in rendered
        assert "aws:region: us-east-1" in rendered

    def test_existing_file_lines_win_over_settings(
        self, infra_tree, monkeypatch,
    ):
        root, proj = infra_tree
        self._stub(monkeypatch, _settings_with_pulumi_state(
            "buzz", "buzz-infra",
            secrets_provider="awskms://alias/SETTINGS-VALUE",
            encrypted_key="SETTINGS-KEY==",
        ))
        out_path = proj / "infra" / "Pulumi.buzz-infra.yaml"
        out_path.parent.mkdir(parents=True)
        out_path.write_text(
            f"secretsprovider: {_PROVIDER}\n"
            f"encryptedkey: {_KEY}\n"
            "config:\n  aws:region: us-east-1\n"
        )
        project_renderer_pulumi.render_pulumi_artifacts(
            "buzz", dict(self._VALUES), root, proj, write=True,
        )
        rendered = out_path.read_text()
        # Operator's live file lines survive; settings values do not leak.
        assert f"secretsprovider: {_PROVIDER}" in rendered
        assert f"encryptedkey: {_KEY}" in rendered
        assert "SETTINGS-VALUE" not in rendered
        assert "SETTINGS-KEY==" not in rendered
        assert rendered.count("secretsprovider:") == 1
