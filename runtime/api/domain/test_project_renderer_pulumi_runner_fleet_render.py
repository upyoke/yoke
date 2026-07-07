"""Render-output coverage for the runner-fleet Pulumi stack type."""

from __future__ import annotations

from yoke_core.domain import project_renderer_pulumi


def test_writes_runner_fleet_stack_type(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    infra = root / "templates" / "webapp" / "infra"
    infra.mkdir(parents=True)
    (infra / "Pulumi.yaml").write_text(
        "name: webapp-infra\nruntime:\n  name: python\n"
    )
    (infra / "Pulumi.runner-fleet-stack.yaml.tmpl").write_text(
        "config:\n"
        "  webapp-infra:project_name: {{project_name}}\n"
        "  webapp-infra:github_repo: {{runner_fleet_repo}}\n"
        "  webapp-infra:runner_labels: '{{runner_fleet_labels_json}}'\n"
        "  webapp-infra:instance_type: {{runner_fleet_instance_type}}\n"
        "  webapp-infra:root_volume_gb: \"{{runner_fleet_root_volume_gb}}\"\n"
    )
    (infra / "__main__.py").write_text("# pulumi entrypoint\n")
    (infra / "webapp_runner_fleet_stack.py").write_text("# runners\n")
    (infra / "webapp_runner_fleet_internals.py").write_text("# internals\n")
    (infra / "webapp_runner_idle_reaper.py").write_text("# reaper\n")
    (infra / "requirements.txt").write_text("pulumi>=3.0.0\n")
    proj = root / "projects" / "buzz"
    proj.mkdir(parents=True)
    monkeypatch.setattr(
        project_renderer_pulumi,
        "gather_pulumi_stacks",
        lambda _project, _root, _settings=None: ["runner-fleet"],
    )
    monkeypatch.setattr(
        project_renderer_pulumi,
        "gather_pulumi_stack_instances",
        lambda _project, _root, _settings=None: [],
    )
    values = {
        "project_name": "buzz",
        "pulumi_runner_fleet_stack_name": "buzz-runner-fleet",
        "runner_fleet_repo": "upyoke/yoke",
        "runner_fleet_labels_json": (
            '["self-hosted","Linux","ARM64","yoke-github-actions"]'
        ),
        "runner_fleet_instance_type": "m7g.2xlarge",
        "runner_fleet_root_volume_gb": "200",
    }

    project_renderer_pulumi.render_pulumi_artifacts(
        "buzz", values, root, proj, write=True,
    )

    infra_dst = proj / "infra"
    assert {p.name for p in infra_dst.iterdir()} == {
        "Pulumi.yaml",
        "Pulumi.buzz-runner-fleet.yaml",
        "__main__.py",
        "webapp_runner_fleet_stack.py",
        "webapp_runner_fleet_internals.py",
        "webapp_runner_idle_reaper.py",
        "requirements.txt",
    }
    rendered = (infra_dst / "Pulumi.buzz-runner-fleet.yaml").read_text()
    assert "webapp-infra:github_repo: upyoke/yoke" in rendered
    assert "webapp-infra:instance_type: m7g.2xlarge" in rendered
    assert 'webapp-infra:root_volume_gb: "200"' in rendered
    assert "{{" not in rendered
