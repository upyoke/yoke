"""Regression tests for Pulumi stack-config divergence warnings.

Covers the Option-(d) behavior added to ``project_renderer_pulumi``: before a
re-render overwrites an existing ``Pulumi.<stack>.yaml``, the renderer warns to
stderr for every ``config:`` value the operator hand-edited away from what the
template would produce (DB settings being the canonical source). The warning is
a diagnostic only — the template rewrite still wins, no merge or preservation
of the config value. Secrets-header preservation is unchanged, and this file
adds the yoke-domain shape (secrets header *below* the config block) that the
existing ``test_preserves_operator_secrets_provider`` does not cover.
"""

from __future__ import annotations

import pytest

from yoke_core.domain import project_renderer_pulumi

# Values passed straight to render_pulumi_artifacts (bypasses gather_*). The
# template renders ``vps_ssh_key_name`` so a later hand-edit can diverge from it.
_VALUES = {
    "aws_region": "us-east-1",
    "vps_ssh_key_name": "my-key-pair",
    "vps_root_volume_gb": "30",
    "pulumi_infra_stack_name": "buzz-infra",
}


class TestParseConfigValues:
    def test_excludes_below_config_secrets_and_strips_quotes(self):
        content = (
            "config:\n"
            "  aws:region: us-east-1\n"
            '  webapp-infra:vps_root_volume_gb: "30"\n'
            "secretsprovider: awskms://alias/x?region=us-east-1\n"
            "encryptedkey: AAA==\n"
        )
        parsed = project_renderer_pulumi._parse_config_values(content)
        assert parsed == {
            "aws:region": "us-east-1",
            "webapp-infra:vps_root_volume_gb": "30",
        }

    def test_excludes_above_config_secrets(self):
        content = (
            "secretsprovider: awskms://alias/x\n"
            "encryptedkey: AAA==\n"
            "config:\n"
            "  aws:region: us-east-1\n"
        )
        parsed = project_renderer_pulumi._parse_config_values(content)
        assert parsed == {"aws:region": "us-east-1"}


class TestWarnOnConfigDivergence:
    def test_returns_diverged_keys_and_warns(self, tmp_path, capsys):
        existing = tmp_path / "Pulumi.x.yaml"
        existing.write_text(
            "config:\n  webapp-infra:vps_ssh_key_name: buzz-ec2-key\n"
        )
        rendered = "config:\n  webapp-infra:vps_ssh_key_name: my-key-pair\n"
        diverged = project_renderer_pulumi._warn_on_config_divergence(
            "buzz", existing, rendered
        )
        assert diverged == ["webapp-infra:vps_ssh_key_name"]
        err = capsys.readouterr().err
        assert "buzz-ec2-key" in err and "my-key-pair" in err
        assert "DB-backed site/environment/capability settings" in err

    def test_matching_value_returns_empty_no_warning(self, tmp_path, capsys):
        existing = tmp_path / "Pulumi.x.yaml"
        existing.write_text("config:\n  webapp-infra:vps_ssh_key_name: same\n")
        rendered = "config:\n  webapp-infra:vps_ssh_key_name: same\n"
        diverged = project_renderer_pulumi._warn_on_config_divergence(
            "buzz", existing, rendered
        )
        assert diverged == []
        assert capsys.readouterr().err == ""

    def test_missing_file_returns_empty(self, tmp_path):
        missing = tmp_path / "absent.yaml"
        diverged = project_renderer_pulumi._warn_on_config_divergence(
            "buzz", missing, "config:\n  aws:region: us-east-1\n"
        )
        assert diverged == []


class TestRenderConfigDivergence:
    @pytest.fixture
    def infra_tree(self, tmp_path, monkeypatch):
        """Single-stack ("infra") project tree whose stack template renders a
        ``vps_ssh_key_name`` config value an operator can later hand-edit."""
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
        root = tmp_path / "repo"
        infra = root / "templates" / "webapp" / "infra"
        infra.mkdir(parents=True)
        (infra / "Pulumi.yaml").write_text(
            "name: webapp-infra\nruntime:\n  name: python\n"
        )
        (infra / "Pulumi.stack.yaml.tmpl").write_text(
            "config:\n"
            "  aws:region: {{aws_region}}\n"
            "  webapp-infra:vps_ssh_key_name: {{vps_ssh_key_name}}\n"
            '  webapp-infra:vps_root_volume_gb: "{{vps_root_volume_gb}}"\n'
        )
        (infra / "__main__.py").write_text("# pulumi entrypoint\n")
        (infra / "webapp_infra_stack.py").write_text("# infra stack\n")
        (infra / "requirements.txt").write_text("pulumi>=3.0.0\n")
        proj = root / "projects" / "buzz"
        proj.mkdir(parents=True)
        return root, proj

    def _render(self, root, proj):
        project_renderer_pulumi.render_pulumi_artifacts(
            "buzz", _VALUES, root, proj, write=True,
        )

    def test_warns_when_operator_hand_edits_config_value(self, infra_tree, capsys):
        root, proj = infra_tree
        self._render(root, proj)
        stack_path = proj / "infra" / "Pulumi.buzz-infra.yaml"

        # Operator hand-edits the config value directly in the stack YAML
        # instead of the DB-backed renderer settings.
        stack_path.write_text(
            stack_path.read_text().replace("my-key-pair", "buzz-ec2-key")
        )
        capsys.readouterr()

        # Re-render — the template still produces my-key-pair, so the operator
        # edit diverges and must be warned about before it is overwritten.
        self._render(root, proj)
        err = capsys.readouterr().err

        assert "WARNING" in err
        assert str(stack_path) in err
        assert "webapp-infra:vps_ssh_key_name" in err
        assert "buzz-ec2-key" in err  # existing operator value
        assert "my-key-pair" in err  # rendered template value
        assert "DB-backed site/environment/capability settings" in err
        assert "render_project buzz --write --only pulumi" in err

        # The rewrite still wins — no merge / preservation of config.
        re_rendered = stack_path.read_text()
        assert "buzz-ec2-key" not in re_rendered
        assert "my-key-pair" in re_rendered

    def test_no_warning_when_value_matches_rendered(self, infra_tree, capsys):
        root, proj = infra_tree
        self._render(root, proj)
        capsys.readouterr()
        # Re-render with identical values — config matches, nothing diverges.
        self._render(root, proj)
        err = capsys.readouterr().err
        assert "WARNING" not in err
        assert "will be overwritten" not in err

    def test_secrets_header_below_config_preserved_without_duplication(
        self, infra_tree, capsys
    ):
        """yoke-domain shape: secretsprovider/encryptedkey sit BELOW config."""
        root, proj = infra_tree
        self._render(root, proj)
        stack_path = proj / "infra" / "Pulumi.buzz-infra.yaml"

        operator_state = (
            "secretsprovider: awskms://alias/yoke-pulumi-state?region=us-east-1\n"
            "encryptedkey: AAABAJxOPAQUE_OPERATOR_KEY==\n"
        )
        stack_path.write_text(stack_path.read_text() + operator_state)
        capsys.readouterr()

        # Re-render twice — preserved lines stay stable (no duplication).
        self._render(root, proj)
        self._render(root, proj)
        text = stack_path.read_text()
        assert text.count("secretsprovider:") == 1
        assert text.count("encryptedkey:") == 1
        assert "awskms://alias/yoke-pulumi-state?region=us-east-1" in text

        # The below-config secrets header is excluded from config comparison —
        # it must never be reported as a divergent config value.
        err = capsys.readouterr().err
        assert "secretsprovider" not in err
        assert "encryptedkey" not in err
        assert "WARNING" not in err
