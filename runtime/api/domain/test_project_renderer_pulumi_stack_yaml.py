"""Tests for rendering a Pulumi stack YAML template."""

from yoke_core.domain import project_renderer_pulumi


def test_substitutes_stack_template_placeholders(tmp_path):
    template = tmp_path / "Pulumi.stack.yaml.tmpl"
    template.write_text(
        "config:\n"
        "  aws:region: {{aws_region}}\n"
        "  webapp-infra:aws_account_id: \"{{aws_account_id}}\"\n"
        "  webapp-infra:kms_key_alias: {{kms_key_alias}}\n"
        "  webapp-infra:domain_name: {{domain_name}}\n"
        "  webapp-infra:origin_host: {{origin_host}}\n"
        "  webapp-infra:project_name: {{project_name}}\n"
        "  webapp-infra:hosted_zone_id: {{hosted_zone_id}}\n"
        "  webapp-infra:certificate_arn: {{certificate_arn}}\n"
        "  webapp-infra:origin_id: {{origin_id}}\n"
        "  webapp-infra:distribution_bucket_name: {{distribution_bucket_name}}\n"
        "  webapp-infra:domain_txt_records: '{{domain_txt_records_json}}'\n"
        "  webapp-infra:domain_mx_records: '{{domain_mx_records_json}}'\n"
        "  webapp-infra:vps_instance_type: {{vps_instance_type}}\n"
        "  webapp-infra:vps_root_volume_gb: \"{{vps_root_volume_gb}}\"\n"
        "  webapp-infra:vps_ssh_key_name: {{vps_ssh_key_name}}\n"
        "  webapp-infra:vps_iam_instance_profile_name: "
        "{{vps_iam_instance_profile_name}}\n"
    )
    values = {
        "aws_region": "us-east-1",
        "aws_account_id": "111122223333",
        "kms_key_alias": "alias/externalwebapp-state",
        "domain_name": "externalwebapp.example.com",
        "origin_host": "origin.example.com",
        "project_name": "externalwebapp",
        "hosted_zone_id": "Z123",
        "certificate_arn": "arn:aws:acm:us-east-1:123:cert/abc",
        "origin_id": "externalwebappinfraDistributionOrigin18BAD744B",
        "distribution_bucket_name": "externalwebapp-distribution-prod",
        "domain_txt_records_json": "[]",
        "domain_mx_records_json": "[]",
        "vps_instance_type": "t3.small",
        "vps_root_volume_gb": "20",
        "vps_ssh_key_name": "externalwebapp-key",
        "vps_iam_instance_profile_name": "externalwebapp-origin-profile",
    }
    rendered = project_renderer_pulumi.render_pulumi_stack_yaml(template, values)
    assert "{{" not in rendered
    assert "}}" not in rendered
    assert "us-east-1" in rendered
    assert "111122223333" in rendered
    assert "alias/externalwebapp-state" in rendered
    assert "t3.small" in rendered
    assert "externalwebappinfraDistributionOrigin18BAD744B" in rendered
    assert "externalwebapp-distribution-prod" in rendered
