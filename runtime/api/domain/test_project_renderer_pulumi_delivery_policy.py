"""Delivery-policy projection from generic Pulumi project settings."""

from __future__ import annotations

import json
from pathlib import Path
import runpy

from yoke_core.domain import project_renderer_pulumi
from yoke_core.domain.project_renderer_pulumi import render_pulumi_stack_yaml
from runtime.api.domain.test_project_renderer_pulumi import (
    _make_project_root,
    _settings_from_context,
)


def test_delivery_ci_cloudfront_id_does_not_require_distribution_bucket(tmp_path):
    base = _settings_from_context(
        "external-webapp",
        {"projectName": "external-webapp"},
        {"cloudfront_id": "EEXTERNAL"},
    )

    result = project_renderer_pulumi.gather_pulumi_values(
        "external-webapp",
        _make_project_root(tmp_path, "external-webapp"),
        base,
    )

    assert result["delivery_cloudfront_distribution_ids_json"] == '["EEXTERNAL"]'
    assert result["delivery_distribution_bucket_names_json"] == "[]"


def test_list_cdn_distribution_flows_to_exact_delivery_policy(tmp_path):
    base = _settings_from_context(
        "externalwebapp", {"projectName": "externalwebapp"}
    )
    base.site_settings["cdn"] = [{"distribution_id": "ELISTSHAPED"}]
    root = _make_project_root(tmp_path, "externalwebapp")

    values = project_renderer_pulumi.gather_pulumi_values(
        "externalwebapp", root, base
    )
    template = (
        Path(__file__).resolve().parents[3]
        / "templates/webapp/infra/Pulumi.registry-stack.yaml.tmpl"
    )
    rendered = render_pulumi_stack_yaml(template, values)
    distribution_ids = json.loads(
        values["delivery_cloudfront_distribution_ids_json"]
    )
    policy_path = template.parent / "webapp_registry_ci_policy.py"
    policy = json.loads(
        runpy.run_path(policy_path)["delivery_policy_json"](
            region="us-east-1",
            account_id="123456789012",
            deploy_namespace="externalwebapp",
            state_bucket="externalwebapp-pulumi-state",
            kms_key_arn="arn:aws:kms:us-east-1:123456789012:key/state-key",
            distribution_bucket_names=[],
            cloudfront_distribution_ids=distribution_ids,
            github_app_private_key_secret_arns=[],
        )
    )

    assert values["cloudfront_id"] == "ELISTSHAPED"
    assert distribution_ids == ["ELISTSHAPED"]
    assert "webapp-infra:cloudfront_distribution_ids: [\"ELISTSHAPED\"]" in rendered
    by_sid = {statement["Sid"]: statement for statement in policy["Statement"]}
    assert by_sid["InvalidateProjectDistributions"]["Resource"] == [
        "arn:aws:cloudfront::123456789012:distribution/ELISTSHAPED"
    ]
