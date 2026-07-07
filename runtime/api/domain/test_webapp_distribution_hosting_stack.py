"""Tests for optional public distribution hosting on the webapp edge stack."""

from __future__ import annotations

import json

from runtime.api.domain.test_webapp_registry_stack import (
    _load_template_module,
    _Recorder,
)


def _infra_stack(monkeypatch, **arg_overrides):
    recorder = _Recorder()
    distribution_module = _load_template_module(
        monkeypatch,
        recorder,
        "webapp_distribution_stack.py",
    )
    dns_module = _load_template_module(
        monkeypatch,
        recorder,
        "webapp_dns_records.py",
    )
    module = _load_template_module(
        monkeypatch,
        recorder,
        "webapp_infra_stack.py",
        extra_modules={
            "webapp_distribution_stack": distribution_module,
            "webapp_dns_records": dns_module,
        },
    )
    kwargs = dict(
        project_name="yoke",
        domain_name="example.com",
        origin_host="origin.example.com",
        hosted_zone_id="Z123",
        certificate_arn="arn:aws:acm:us-east-1:123456789012:certificate/abc",
        origin_id="yoke-origin",
    )
    kwargs.update(arg_overrides)
    stack = module.WebappInfraStack(
        "yoke-infra",
        module.WebappInfraArgs(**kwargs),
    )
    return recorder, stack


def _api_stack(monkeypatch, **arg_overrides):
    recorder = _Recorder()
    distribution_module = _load_template_module(
        monkeypatch,
        recorder,
        "webapp_distribution_stack.py",
    )
    module = _load_template_module(
        monkeypatch,
        recorder,
        "webapp_api_stack.py",
        extra_modules={"webapp_distribution_stack": distribution_module},
    )
    kwargs = dict(
        project_name="yoke",
        environment="prod",
        domain_name="example.com",
        api_host="api.example.com",
        origin_host="origin.example.com",
        hosted_zone_id="Z123",
        origin_ip="198.51.100.7",
        api_origin_port=80,
    )
    kwargs.update(arg_overrides)
    stack = module.WebappApiStack("api", module.WebappApiArgs(**kwargs))
    return recorder, stack


def test_distribution_hosting_is_absent_without_bucket_config(monkeypatch):
    recorder, stack = _infra_stack(monkeypatch)
    distribution = recorder.single("distribution")
    assert distribution.kwargs["ordered_cache_behaviors"] == []
    assert stack.distribution_bucket is None
    assert recorder.exports["distributionBucketName"] == ""


def test_distribution_hosting_adds_static_origin_and_path_behaviors(monkeypatch):
    recorder, stack = _infra_stack(
        monkeypatch,
        distribution_bucket_name="example-distribution-prod",
    )

    bucket = recorder.single("distributionBucket")
    assert bucket.kwargs["bucket"] == "example-distribution-prod"

    block = recorder.single("distributionBucketPublicAccessBlock")
    assert block.kwargs["block_public_acls"] is True
    assert block.kwargs["block_public_policy"] is True
    assert block.kwargs["ignore_public_acls"] is True
    assert block.kwargs["restrict_public_buckets"] is True
    origin_access = recorder.single("distributionOriginAccess")
    assert origin_access.kwargs["comment"] == (
        "yoke-distribution-static read access"
    )

    distribution = recorder.single("distribution")
    origins = distribution.kwargs["origins"]
    assert [origin.kwargs["origin_id"] for origin in origins] == [
        "yoke-origin",
        "yoke-distribution-static",
    ]
    static_origin = origins[1]
    assert (
        static_origin.kwargs["s3_origin_config"].kwargs["origin_access_identity"]
        .value
        == "distributionOriginAccess.cloudfront_access_identity_path"
    )
    assert "origin_access_control_id" not in static_origin.kwargs
    behaviors = distribution.kwargs["ordered_cache_behaviors"]
    assert [behavior.kwargs["path_pattern"] for behavior in behaviors] == [
        "install",
        "dist/*",
        "simple/*",
    ]
    assert all(
        behavior.kwargs["target_origin_id"] == "yoke-distribution-static"
        for behavior in behaviors
    )
    assert all(
        behavior.kwargs["cache_policy_id"]
        == "658327ea-f89d-4fab-a63d-7e88639e58f6"
        for behavior in behaviors
    )
    # Only the PEP 503 simple/* behavior rewrites directory URLs to index.html.
    simple_behavior = next(
        b for b in behaviors if b.kwargs["path_pattern"] == "simple/*"
    )
    assert (
        simple_behavior.kwargs["function_associations"][0].kwargs["event_type"]
        == "viewer-request"
    )
    assert all(
        "function_associations" not in b.kwargs
        for b in behaviors
        if b.kwargs["path_pattern"] != "simple/*"
    )

    policy = recorder.single("distributionBucketPolicy")
    policy_payload = json.loads(policy.kwargs["policy"])
    statement = policy_payload["Statement"][0]
    assert statement["Principal"] == {"AWS": "distributionOriginAccess.iam_arn"}
    assert statement["Action"] == "s3:GetObject"
    assert statement["Resource"] == "arn:aws:s3:::example-distribution-prod/*"
    assert "Condition" not in statement
    assert stack.distribution_bucket is bucket
    assert recorder.exports["distributionBucketName"] == (
        "example-distribution-prod"
    )


def test_api_edge_hosts_distribution_paths_on_environment_hostname(monkeypatch):
    recorder, stack = _api_stack(
        monkeypatch,
        distribution_bucket_name="example-distribution-prod",
        distribution_origin_id="yoke-prod-distribution-static",
    )

    distribution = recorder.single("apiDistribution")
    assert distribution.kwargs["aliases"] == ["api.example.com"]
    assert [origin.kwargs["origin_id"] for origin in distribution.kwargs["origins"]] == [
        "yoke-prod-api-origin",
        "yoke-prod-distribution-static",
    ]
    behaviors = distribution.kwargs["ordered_cache_behaviors"]
    assert [behavior.kwargs["path_pattern"] for behavior in behaviors] == [
        "install",
        "dist/*",
        "simple/*",
    ]
    assert recorder.single("distributionBucket").kwargs["bucket"] == (
        "example-distribution-prod"
    )
    assert stack.distribution_bucket_policy is recorder.single(
        "distributionBucketPolicy"
    )
    assert recorder.exports["distributionBucketName"] == (
        "example-distribution-prod"
    )
