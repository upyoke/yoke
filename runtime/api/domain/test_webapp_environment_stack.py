"""Tests for the environment stack's origin runtime substrate.

Loads the real ``webapp_environment_stack.py`` template module under the fake
``pulumi`` / ``pulumi_aws`` harness from ``test_webapp_registry_stack.py``.
The environment-stack tests substitute sibling child-stack modules with
recording fakes so composition is asserted without faking their AWS surfaces.
"""

from __future__ import annotations

from runtime.api.domain.webapp_environment_stack_test_support import (
    _environment_stack as _environment_stack,
    _fake_sibling_modules as _fake_sibling_modules,
    _recording_args_class as _recording_args_class,
)


import json


class TestEnvironmentOriginRuntimeSubstrate:
    def test_reads_origin_network_from_standalone_stack(self, monkeypatch):
        recorder, stack = _environment_stack(monkeypatch)
        assert recorder.stack_references == ["yoke-platform-vps"]
        assert recorder.stack_reference_outputs == [
            ("yoke-platform-vps", "vpsElasticIpAddress"),
            ("yoke-platform-vps", "vpsSecurityGroupId"),
        ]
        assert recorder.exports["originElasticIpAddress"].value == "198.51.100.7"
        assert recorder.exports["originSecurityGroupId"].value == "sg-fake"
        assert stack.registered_outputs["originElasticIpAddress"].value == (
            "198.51.100.7"
        )

    def test_database_allows_origin_and_configured_service_groups(self, monkeypatch):
        recorder, _stack = _environment_stack(monkeypatch)
        database = recorder.single("database")
        assert len(database.args.allowed_security_group_ids) == 2
        assert database.args.allowed_security_group_ids[0].value == "sg-fake"
        assert database.args.allowed_security_group_ids[1] == "sg-tenant-provisioner"
        assert recorder.single("api").args.origin_ip.value == "198.51.100.7"

    def test_creates_core_log_group(self, monkeypatch):
        recorder, _stack = _environment_stack(monkeypatch)
        log_group = recorder.single("coreLogGroup")
        assert log_group.kwargs["name"] == "/yoke/prod/core"
        assert log_group.kwargs["retention_in_days"] == 30
        assert log_group.kwargs["tags"] == {
            "project": "yoke",
            "environment": "prod",
        }

    def test_origin_role_grants_runtime_permissions(self, monkeypatch):
        recorder, _stack = _environment_stack(monkeypatch)
        role = recorder.single("originRole")
        trust = json.loads(role.kwargs["assume_role_policy"])
        assert trust["Statement"][0]["Principal"] == {
            "Service": "ec2.amazonaws.com",
        }

        policy = recorder.single("originRolePolicy")
        statements = json.loads(policy.kwargs["policy"])["Statement"]
        assert statements[0]["Action"] == ["ecr:GetAuthorizationToken"]
        assert statements[0]["Resource"] == "*"
        assert statements[1]["Action"] == [
            "ecr:BatchGetImage",
            "ecr:GetDownloadUrlForLayer",
            "ecr:BatchCheckLayerAvailability",
        ]
        assert statements[1]["Resource"] == (
            "arn:aws:ecr:us-east-1:123456789012:repository/yoke-core"
        )
        assert statements[2]["Action"] == [
            "logs:CreateLogStream",
            "logs:PutLogEvents",
            "logs:DescribeLogStreams",
        ]
        assert statements[2]["Resource"] == [
            "coreLogGroup.arn",
            "coreLogGroup.arn:*",
        ]
        assert statements[3]["Action"] == [
            "secretsmanager:DescribeSecret",
            "secretsmanager:GetSecretValue",
        ]
        assert statements[3]["Resource"] == (
            "arn:aws:secretsmanager:us-east-1:123456789012:secret:yoke-prod-db"
        )
        assert statements[4]["Action"] == ["s3:PutObject", "s3:GetObject"]
        assert statements[4]["Resource"] == ("arn:aws:s3:::yoke-prod-artifacts/*")

    def test_origin_role_attaches_session_manager_access(self, monkeypatch):
        recorder, _stack = _environment_stack(monkeypatch)
        attachment = recorder.single("originSsmManagedInstancePolicy")
        assert attachment.kwargs["role"].value == "originRole.name"
        assert attachment.kwargs["policy_arn"].endswith(
            ":policy/AmazonSSMManagedInstanceCore"
        )

    def test_container_repository_name_defaults_to_project_core(
        self,
        monkeypatch,
    ):
        recorder, stack = _environment_stack(monkeypatch)
        assert recorder.exports["containerRepositoryName"] == "yoke-core"
        assert stack.registered_outputs["containerRepositoryName"] == ("yoke-core")
        assert {"coreLogGroupName", "originInstanceProfileName"} <= set(
            recorder.exports
        )
        assert recorder.exports["coreLogGroupName"] == "/yoke/prod/core"
        assert recorder.exports["originInstanceProfileName"].value == (
            "originInstanceProfile.name"
        )

    def test_container_repository_name_override(self, monkeypatch):
        recorder, _stack = _environment_stack(
            monkeypatch,
            container_repository_name="custom-repo",
        )
        assert recorder.exports["containerRepositoryName"] == "custom-repo"
        policy = recorder.single("originRolePolicy").kwargs["policy"]
        assert "repository/custom-repo" in policy

    def test_distribution_config_passes_to_api_edge(self, monkeypatch):
        recorder, _stack = _environment_stack(
            monkeypatch,
            distribution_bucket_name="example-distribution-prod",
            distribution_origin_id="yoke-prod-distribution-static",
            distribution_base_url="https://api.example.com",
            distribution_repository_variable_namespace="yoke",
            github_repo="acme/yoke",
        )
        api = recorder.single("api")
        assert api.args.distribution_bucket_name == "example-distribution-prod"
        assert api.args.distribution_origin_id == "yoke-prod-distribution-static"
        assert recorder.distribution_variable_kwargs == {
            "variable_namespace": "yoke",
            "environment": "prod",
            "github_repo": "acme/yoke",
            "github_api_url": "https://api.github.com",
            "base_url": "https://api.example.com",
            "bucket": "example-distribution-prod",
            "cloudfront_id": "distribution-id",
            "origin_id": "yoke-prod-distribution-static",
            "child_opts": recorder.distribution_variable_kwargs["child_opts"],
        }


class TestArtifactsBucket:
    def test_bucket_is_private_tagged_and_named(self, monkeypatch):
        recorder, stack = _environment_stack(monkeypatch)
        bucket = recorder.single("artifactsBucket")
        assert bucket.kwargs["bucket"] == "yoke-prod-artifacts"
        assert bucket.kwargs["tags"] == {
            "project": "yoke",
            "environment": "prod",
        }
        assert stack.artifacts_bucket is bucket

        block = recorder.single("artifactsBucketPublicAccessBlock")
        assert block.kwargs["block_public_acls"] is True
        assert block.kwargs["block_public_policy"] is True
        assert block.kwargs["ignore_public_acls"] is True
        assert block.kwargs["restrict_public_buckets"] is True

    def test_bucket_keeps_evidence_without_lifecycle_expiry(self, monkeypatch):
        recorder, _stack = _environment_stack(monkeypatch)
        assert not [
            resource
            for resource in recorder.resources
            if "Lifecycle" in getattr(resource, "resource_type", "")
        ]

    def test_bucket_name_exported(self, monkeypatch):
        recorder, stack = _environment_stack(monkeypatch)
        assert recorder.exports["artifactsBucketName"] == ("yoke-prod-artifacts")
        assert stack.registered_outputs["artifactsBucketName"] == (
            "yoke-prod-artifacts"
        )

    def test_bucket_name_tracks_environment(self, monkeypatch):
        recorder, _stack = _environment_stack(
            monkeypatch,
            environment="stage",
        )
        assert recorder.exports["artifactsBucketName"] == ("yoke-stage-artifacts")
        policy = recorder.single("originRolePolicy").kwargs["policy"]
        assert "arn:aws:s3:::yoke-stage-artifacts/*" in policy


class TestEphemeralPreviewSubstrate:
    def test_preview_domain_creates_wildcard_record(self, monkeypatch):
        recorder, stack = _environment_stack(
            monkeypatch,
            ephemeral_preview_domain="preview.example.com",
        )
        record = recorder.single("ephemeralWildcardRecord")
        assert record.kwargs["zone_id"] == "Z123"
        assert record.kwargs["name"] == "*.preview.example.com"
        assert record.kwargs["type"] == "A"
        assert record.kwargs["ttl"] == 300
        assert record.kwargs["records"][0].value == "198.51.100.7"
        assert stack.ephemeral_wildcard_record is record

    def test_preview_domain_grants_dns01_route53_statements(self, monkeypatch):
        recorder, _stack = _environment_stack(
            monkeypatch,
            ephemeral_preview_domain="preview.example.com",
        )
        policy = recorder.single("originRolePolicy")
        statements = json.loads(policy.kwargs["policy"])["Statement"]
        assert statements[5]["Action"] == [
            "route53:ListHostedZones",
            "route53:GetChange",
        ]
        assert statements[5]["Resource"] == "*"
        assert statements[6]["Action"] == [
            "route53:ChangeResourceRecordSets",
            "route53:ListResourceRecordSets",
        ]
        assert statements[6]["Resource"] == "arn:aws:route53:::hostedzone/Z123"

    def test_preview_domain_exported(self, monkeypatch):
        recorder, stack = _environment_stack(
            monkeypatch,
            ephemeral_preview_domain="preview.example.com",
        )
        assert recorder.exports["ephemeralPreviewDomain"] == ("preview.example.com")
        assert stack.registered_outputs["ephemeralPreviewDomain"] == (
            "preview.example.com"
        )

    def test_unset_preview_domain_keeps_substrate_absent(self, monkeypatch):
        recorder, stack = _environment_stack(monkeypatch)
        names = {resource.resource_name for resource in recorder.resources}
        assert "ephemeralWildcardRecord" not in names
        assert stack.ephemeral_wildcard_record is None
        policy = recorder.single("originRolePolicy")
        statements = json.loads(policy.kwargs["policy"])["Statement"]
        assert len(statements) == 5
        assert "route53" not in policy.kwargs["policy"]
        assert recorder.exports["ephemeralPreviewDomain"] == ""
