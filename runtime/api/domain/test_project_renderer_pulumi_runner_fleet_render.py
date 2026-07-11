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
        "  aws:region: {{runner_fleet_aws_region}}\n"
        "  webapp-infra:project_name: {{project_name}}\n"
        "  webapp-infra:aws_capability: {{runner_fleet_aws_capability}}\n"
        "  webapp-infra:github_capability: {{runner_fleet_github_capability}}\n"
        "  webapp-infra:github_app_environment: {{runner_fleet_github_app_environment}}\n"
        "  webapp-infra:github_repo: {{runner_fleet_repo}}\n"
        "  webapp-infra:github_repo_owner: {{runner_fleet_github_repo_owner}}\n"
        "  webapp-infra:github_repo_name: {{runner_fleet_github_repo_name}}\n"
        "  webapp-infra:github_installation_id: {{runner_fleet_github_installation_id}}\n"
        "  webapp-infra:github_repository_id: {{runner_fleet_github_repository_id}}\n"
        "  webapp-infra:github_app_issuer: {{runner_fleet_github_app_issuer}}\n"
        "  webapp-infra:github_api_url: {{runner_fleet_github_api_url}}\n"
        "  webapp-infra:github_web_url: {{runner_fleet_github_web_url}}\n"
        "  webapp-infra:github_private_key_secret_arn: {{runner_fleet_github_private_key_secret_arn}}\n"
        "  webapp-infra:runner_labels: '{{runner_fleet_labels_json}}'\n"
        "  webapp-infra:runner_variable_name: {{runner_fleet_variable_name}}\n"
        "  webapp-infra:routing_enabled: \"{{runner_fleet_routing_enabled}}\"\n"
        "  webapp-infra:instance_type: {{runner_fleet_instance_type}}\n"
        "  webapp-infra:root_volume_gb: \"{{runner_fleet_root_volume_gb}}\"\n"
        "  webapp-infra:deployment_ssh_stack_names: '{{runner_fleet_deployment_ssh_stack_names_json}}'\n"
    )
    (infra / "__main__.py").write_text("# pulumi entrypoint\n")
    (infra / "webapp_runner_fleet_stack.py").write_text("# runners\n")
    (infra / "webapp_runner_authority_intent.py").write_text("# intent\n")
    (infra / "webapp_runner_fleet_config.py").write_text("# config\n")
    (infra / "webapp_runner_fleet_internals.py").write_text("# internals\n")
    (infra / "webapp_runner_fleet_iam.py").write_text("# iam\n")
    (infra / "webapp_runner_fleet_network.py").write_text("# network\n")
    (infra / "webapp_runner_github_broker_stack.py").write_text("# broker\n")
    (infra / "webapp_runner_github_state.py").write_text("# state\n")
    (infra / "webapp_runner_github_webhook.py").write_text("# webhook\n")
    (infra / "webapp_github_repository_provider.py").write_text(
        "# github provider\n"
    )
    (infra / "webapp_runner_aws_state.mjs").write_text("// aws state\n")
    (infra / "webapp_runner_github_api.mjs").write_text("// github api\n")
    (infra / "webapp_runner_github_broker.mjs").write_text("// broker\n")
    (infra / "webapp_runner_termination.mjs").write_text("// termination\n")
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
        "runner_fleet_aws_capability": "aws-admin",
        "runner_fleet_aws_region": "us-east-1",
        "runner_fleet_repo": "upyoke/yoke",
        "runner_fleet_github_capability": "github",
        "runner_fleet_github_app_environment": "buzz-api-stage",
        "runner_fleet_github_repo_owner": "upyoke",
        "runner_fleet_github_repo_name": "yoke",
        "runner_fleet_github_installation_id": "123456",
        "runner_fleet_github_repository_id": "789012",
        "runner_fleet_github_app_issuer": "Iv1.runner-fleet",
        "runner_fleet_github_api_url": "https://api.github.com",
        "runner_fleet_github_web_url": "https://github.com",
        "runner_fleet_github_private_key_secret_arn": (
            "arn:aws:secretsmanager:us-east-1:123456789012:"
            "secret:yoke-github-app-AbCdEf"
        ),
        "runner_fleet_labels_json": (
            '["self-hosted","Linux","ARM64","yoke-github-actions"]'
        ),
        "runner_fleet_variable_name": "YOKE_LINUX_RUNS_ON",
        "runner_fleet_routing_enabled": "true",
        "runner_fleet_instance_type": "m7g.2xlarge",
        "runner_fleet_root_volume_gb": "200",
        "runner_fleet_deployment_ssh_stack_names_json": (
            '["buzz-prod","buzz-stage","yoke-platform-vps"]'
        ),
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
        "webapp_runner_authority_intent.py",
        "webapp_runner_fleet_config.py",
        "webapp_runner_fleet_internals.py",
        "webapp_runner_fleet_iam.py",
        "webapp_runner_fleet_network.py",
        "webapp_runner_github_broker_stack.py",
        "webapp_runner_github_state.py",
        "webapp_runner_github_webhook.py",
        "webapp_runner_aws_state.mjs",
        "webapp_runner_github_api.mjs",
        "webapp_runner_github_broker.mjs",
        "webapp_runner_termination.mjs",
        "requirements.txt",
        "webapp_github_repository_provider.py",
    }
    rendered = (infra_dst / "Pulumi.buzz-runner-fleet.yaml").read_text()
    assert "webapp-infra:github_repo: upyoke/yoke" in rendered
    assert "aws:region: us-east-1" in rendered
    assert "webapp-infra:aws_capability: aws-admin" in rendered
    assert "webapp-infra:github_capability: github" in rendered
    assert "webapp-infra:instance_type: m7g.2xlarge" in rendered
    assert "webapp-infra:github_repository_id: 789012" in rendered
    assert "webapp-infra:github_web_url: https://github.com" in rendered
    assert "webapp-infra:runner_variable_name: YOKE_LINUX_RUNS_ON" in rendered
    assert 'webapp-infra:routing_enabled: "true"' in rendered
    assert 'webapp-infra:root_volume_gb: "200"' in rendered
    assert (
        "webapp-infra:deployment_ssh_stack_names: "
        "'[\"buzz-prod\",\"buzz-stage\",\"yoke-platform-vps\"]'"
    ) in rendered
    assert "{{" not in rendered
