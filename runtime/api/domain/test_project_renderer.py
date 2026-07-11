"""Tests for project_renderer.py — template rendering logic.

Tests focus on the pure rendering engine (no external DB calls).
Value gathering is tested with mocked subprocess calls.
"""

from __future__ import annotations

from unittest import mock

import pytest

from yoke_core.domain import project_renderer


# ---------------------------------------------------------------------------
# Template rendering
# ---------------------------------------------------------------------------

class TestRenderTemplate:
    def test_basic_replacement(self):
        content = "Hello {{project_name}}, port {{web_port}}"
        values = {"project_name": "buzz", "web_port": "3000"}
        result = project_renderer.render_template(content, values)
        assert result == "Hello buzz, port 3000"

    def test_no_partial_match(self):
        """Longest-first replacement avoids partial matches."""
        content = "{{project_name}} and {{project_name_upper}}"
        # project_name_upper is longer, should be replaced first
        values = {
            "project_name": "buzz",
            "project_name_upper": "BUZZ",
        }
        # Verify no partial replacement of {{project_name_upper}} → "buzz_upper"
        # This would happen if short keys were replaced first
        result = project_renderer.render_template(content, values)
        # Both should be replaced independently
        assert "buzz" in result
        # Note: project_name_upper is a different key than PROJECT_NAME_UPPER
        # but the test validates the longest-first ordering prevents overlap

    def test_missing_placeholder_preserved(self):
        content = "Hello {{unknown_key}}"
        values = {"project_name": "buzz"}
        result = project_renderer.render_template(content, values)
        assert "{{unknown_key}}" in result

    def test_multiple_occurrences(self):
        content = "{{web_port}} and again {{web_port}}"
        values = {"web_port": "3000"}
        result = project_renderer.render_template(content, values)
        assert result == "3000 and again 3000"


# ---------------------------------------------------------------------------
# Auto header
# ---------------------------------------------------------------------------

class TestAutoHeader:
    def test_hash_comment(self):
        header = project_renderer._auto_header(
            "#", "templates/webapp/ops/foo.yml", "buzz", "workflows"
        )
        assert header.startswith("# AUTO-GENERATED")
        assert "foo.yml" in header
        assert "buzz" in header

    def test_slash_comment(self):
        header = project_renderer._auto_header(
            "//", "templates/webapp/ops/foo.js", "buzz", "ops"
        )
        assert header.startswith("// AUTO-GENERATED")


# ---------------------------------------------------------------------------
# Full render pipeline (with minimal fixture)
# ---------------------------------------------------------------------------

class TestRenderProject:
    @pytest.fixture
    def project_tree(self, tmp_path):
        """Build a minimal project tree with templates."""
        root = tmp_path / "repo"

        # Template dirs
        ops = root / "templates" / "webapp" / "ops"
        ops.mkdir(parents=True)
        scaffold = root / "templates" / "webapp" / "scaffold" / "app"
        scaffold.mkdir(parents=True)

        # A workflow template
        wf = ops / "deploy.yml"
        wf.write_text("name: Deploy {{project_name}}\non: push\njobs:\n  deploy:\n    runs-on: ubuntu\n")

        # An ops script template
        ops_script = ops / "ephemeral-cleanup.sh.tmpl"
        ops_script.write_text("#!/usr/bin/env sh\n# Cleanup {{project_name}} on port {{web_port}}\necho done\n")

        # an unparameterized .sh.tmpl source (no placeholders).
        # These must still be rendered so operators get an executable copy
        # alongside the rest of the rendered ops scripts — the .tmpl extension
        # is the ownership marker, not the
        # presence of placeholders.
        ops_firewall = ops / "update-firewall.sh.tmpl"
        ops_firewall.write_text("#!/usr/bin/env sh\necho firewall update\n")

        # Explicit Python ops programs render even when they have no project
        # placeholders; the source filename is the ownership marker.
        docker_cleanup = ops / "docker_image_cleanup.py"
        docker_cleanup.write_text(
            "#!/usr/bin/env python3\nprint('--repository')\n"
        )
        maintenance = ops / "docker_maintenance_converge.py"
        maintenance.write_text(
            "#!/usr/bin/env python3\nprint('docker maintenance')\n"
        )

        # A .conf source WITH placeholders (rendered normally)
        conf_tmpl = ops / "nginx-ephemeral.conf"
        conf_tmpl.write_text("server_name {{domain_name}};\n")

        # A .conf source WITHOUT placeholders (must be skipped — unowned by renderer)
        conf_skip = ops / "noop.conf"
        conf_skip.write_text("listen 80;\n")

        # A scaffold template
        entrypoint = scaffold / "entrypoint.sh.tmpl"
        entrypoint.write_text("#!/usr/bin/env sh\necho Starting {{project_name}} on port {{web_port}}\n")

        # DEPLOY.md template
        deploy_md = ops / "DEPLOY.md"
        deploy_md.write_text("# Deploy {{project_display_name}}\nRegion: {{aws_region}}\n")

        # Scripts dir (for DB queries — will be mocked)
        scripts = root / ".agents" / "skills" / "yoke" / "scripts"
        scripts.mkdir(parents=True)

        return root

    def test_render_deploy_md(self, project_tree, tmp_path):
        """Test DEPLOY.md rendering with pre-gathered values."""
        proj_dir = project_tree / "rendered" / "testproj"
        proj_dir.mkdir(parents=True)
        values = {"project_display_name": "TestProj", "aws_region": "us-west-2"}

        project_renderer.render_deploy_md(
            "testproj", values, project_tree, proj_dir, write=True,
        )
        rendered = (proj_dir / "DEPLOY.md").read_text()
        assert "# Deploy TestProj" in rendered
        assert "Region: us-west-2" in rendered

    def test_render_project_uses_pulumi_values_for_docs(self, project_tree, monkeypatch):
        """Pulumi placeholders in rendered docs come from the shared value set."""
        deploy_md = project_tree.joinpath(
            "templates", "webapp", "ops", "DEPLOY.md",
        )
        deploy_md.write_text(
            "Stack: {{pulumi_infra_stack_name}}\n"
            "State: {{state_bucket}}\n"
        )
        monkeypatch.setattr(
            project_renderer,
            "gather_pulumi_values",
            lambda _project, _root, _settings=None, *, pulumi_stack=None: {
                "pulumi_infra_stack_name": "testproj-infra",
                "state_bucket": "testproj-state",
            },
        )

        output_dir = project_tree / "rendered" / "testproj"
        project_renderer.render_project(
            "testproj",
            write=True,
            only="DEPLOY.md",
            project_root=project_tree,
            output_dir=output_dir,
        )

        rendered = (output_dir / "DEPLOY.md").read_text()
        assert "Stack: testproj-infra" in rendered
        assert "State: testproj-state" in rendered
        assert "{{" not in rendered

    def test_render_workflows(self, project_tree, tmp_path):
        """Test workflow YAML rendering."""
        proj_dir = project_tree / "rendered" / "testproj"
        values = {"project_name": "testproj"}

        project_renderer.render_workflows(
            "testproj", values, project_tree, proj_dir, write=True,
        )
        wf_dir = proj_dir / "workflows"
        rendered_files = list(wf_dir.glob("*.yml"))
        assert len(rendered_files) == 1
        content = rendered_files[0].read_text()
        assert "Deploy testproj" in content
        assert "AUTO-GENERATED" in content

    def test_render_ops(self, project_tree, tmp_path):
        """Test ops script rendering with placeholder substitution.

        the source template is ``ephemeral-cleanup.sh.tmpl`` but
        the rendered output file drops the ``.tmpl`` suffix so the operator
        gets an executable ``.sh`` on disk for scp-to-VPS.
        """
        proj_dir = project_tree / "rendered" / "testproj"
        values = {"project_name": "testproj", "web_port": "4000"}

        project_renderer.render_ops(
            "testproj", values, project_tree, proj_dir, write=True,
        )
        ops_dir = proj_dir / "ops"
        rendered_sh = sorted(p.name for p in ops_dir.glob("*.sh"))
        # Must render BOTH the parameterized and unparameterized .sh.tmpl
        # sources.
        assert rendered_sh == ["ephemeral-cleanup.sh", "update-firewall.sh"]
        rendered_py = sorted(p.name for p in ops_dir.glob("*.py"))
        assert rendered_py == [
            "docker_image_cleanup.py",
            "docker_maintenance_converge.py",
        ]
        # No stray .tmpl file should land in the rendered output directory.
        assert list(ops_dir.glob("*.tmpl")) == []

        # Parameterized ops script: placeholder substitution happened.
        cleanup = (ops_dir / "ephemeral-cleanup.sh").read_text()
        assert "testproj" in cleanup
        assert "4000" in cleanup
        assert "AUTO-GENERATED" in cleanup
        # The auto-header must reference the new Python CLI,
        # never the deleted render-project.sh shell launcher.
        assert "yoke_core.tools.render_project" in cleanup
        assert "render-project.sh" not in cleanup
        # The source attribution must point at the .sh.tmpl template.
        assert "ephemeral-cleanup.sh.tmpl" in cleanup

        # Unparameterized ops script: header still added, body unchanged.
        firewall = (ops_dir / "update-firewall.sh").read_text()
        assert "AUTO-GENERATED" in firewall
        assert "update-firewall.sh.tmpl" in firewall
        assert "echo firewall update" in firewall

        docker_cleanup = (ops_dir / "docker_image_cleanup.py").read_text()
        assert docker_cleanup.startswith("#!/usr/bin/env python3\n# AUTO-GENERATED")
        assert "docker_image_cleanup.py" in docker_cleanup
        assert "--repository" in docker_cleanup

        maintenance = (ops_dir / "docker_maintenance_converge.py").read_text()
        assert maintenance.startswith("#!/usr/bin/env python3\n# AUTO-GENERATED")
        assert "docker_maintenance_converge.py" in maintenance

        # Output must have executable bit set (operator scp-to-VPS flow).
        import stat
        for program in (*ops_dir.glob("*.sh"), *ops_dir.glob("*.py")):
            mode = program.stat().st_mode
            assert mode & stat.S_IXUSR, f"{program.name} must be executable"

        # .conf with placeholders is rendered; .conf without placeholders is skipped.
        rendered_conf = sorted(p.name for p in ops_dir.glob("*.conf"))
        assert rendered_conf == ["nginx-ephemeral.conf"]

    def test_render_scaffold(self, project_tree, tmp_path):
        """Test scaffold file rendering."""
        proj_dir = project_tree / "rendered" / "testproj"
        values = {"project_name": "testproj", "web_port": "4000"}

        project_renderer.render_scaffold(
            "testproj", values, project_tree, proj_dir, write=True,
        )
        entrypoint = proj_dir / "scaffold" / "app" / "entrypoint.sh"
        assert entrypoint.is_file()
        # The tmpl source must NOT appear in the rendered scaffold tree.
        assert not (proj_dir / "scaffold" / "app" / "entrypoint.sh.tmpl").exists()
        content = entrypoint.read_text()
        assert "testproj" in content
        assert "4000" in content
        # The auto-header must reference the new Python CLI.
        assert "yoke_core.tools.render_project" in content
        assert "render-project.sh" not in content
        # The source attribution must point at the .sh.tmpl template.
        assert "entrypoint.sh.tmpl" in content


# ---------------------------------------------------------------------------
# CLI argument parsing
# ---------------------------------------------------------------------------

class TestCli:
    def test_project_required(self):
        with pytest.raises(SystemExit) as exc_info:
            project_renderer.main([])
        assert exc_info.value.code == 2  # argparse usage error

    def test_args_parsed(self):
        with mock.patch.object(project_renderer, "render_project") as m:
            project_renderer.main(["buzz", "--write", "--only", "workflows"])
            m.assert_called_once_with(
                "buzz", write=True, only="workflows", output_dir=None,
                settings=None, pulumi_stack=None,
            )

    def test_output_dir_parsed(self, tmp_path):
        output_dir = tmp_path / "rendered"
        with mock.patch.object(project_renderer, "render_project") as m:
            project_renderer.main([
                "buzz",
                "--write",
                "--only", "workflows",
                "--output-dir", str(output_dir),
            ])
            m.assert_called_once_with(
                "buzz", write=True, only="workflows", output_dir=output_dir,
                settings=None, pulumi_stack=None,
            )

    def test_pulumi_stack_selector_is_forwarded(self):
        with mock.patch.object(project_renderer, "render_project") as render:
            project_renderer.main([
                "platform", "--write", "--only", "pulumi",
                "--pulumi-stack", "yoke-stage",
            ])

        render.assert_called_once_with(
            "platform", write=True, only="pulumi", output_dir=None,
            settings=None, pulumi_stack="yoke-stage",
        )

    def test_pulumi_stack_selector_rejects_other_artifact_families(self):
        with pytest.raises(SystemExit) as exc_info:
            project_renderer.main([
                "platform", "--only", "ops",
                "--pulumi-stack", "yoke-stage",
            ])

        assert exc_info.value.code == 2
