"""Tests for the environment stack's origin runtime substrate + VPS profile.

Loads the real ``webapp_environment_stack.py`` / ``webapp_vps_stack.py``
template modules under the fake ``pulumi`` / ``pulumi_aws`` harness from
``test_webapp_registry_stack.py``. The environment-stack tests substitute the
sibling child-stack modules with recording fakes so composition (log group,
IAM role/profile, repository-name defaulting, VPS wiring) is asserted without
faking the entire child-stack AWS surface.
"""

from __future__ import annotations

import json
import types

from runtime.api.domain.test_webapp_registry_stack import (
    _load_template_module,
    _Recorder,
)


def _recording_args_class():
    class _RecordingArgs:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    return _RecordingArgs


def _fake_sibling_modules(recorder):
    vps = types.ModuleType("webapp_vps_stack")

    class _FakeVpsStack:
        def __init__(self, name, args, opts=None):
            self.resource_type = "fake:WebappVpsStack"
            self.resource_name = name
            self.args = args
            self.opts = opts
            self.security_group = types.SimpleNamespace(id="sg-fake")
            self.elastic_ip = types.SimpleNamespace(public_ip="198.51.100.7")
            recorder.resources.append(self)

    vps.WebappVpsArgs = _recording_args_class()
    vps.WebappVpsStack = _FakeVpsStack

    database = types.ModuleType("webapp_database_stack")
    database.DEFAULT_SECONDS_UNTIL_AUTO_PAUSE = 1800

    class _FakeDatabaseStack:
        def __init__(self, name, args, opts=None):
            self.resource_type = "fake:WebappDatabaseStack"
            self.resource_name = name
            self.args = args
            self.cluster = types.SimpleNamespace(endpoint="db.internal.example")
            self.master_secret_arn = (
                "arn:aws:secretsmanager:us-east-1:123456789012:secret:yoke-prod-db"
            )
            recorder.resources.append(self)

    database.WebappDatabaseArgs = _recording_args_class()
    database.WebappDatabaseStack = _FakeDatabaseStack

    api = types.ModuleType("webapp_api_stack")

    class _FakeApiStack:
        def __init__(self, name, args, opts=None):
            self.resource_type = "fake:WebappApiStack"
            self.resource_name = name
            self.args = args
            self.distribution = types.SimpleNamespace(id="distribution-id")
            recorder.resources.append(self)

    api.WebappApiArgs = _recording_args_class()
    api.WebappApiStack = _FakeApiStack

    distribution_variables = types.ModuleType(
        "webapp_distribution_github_variables"
    )

    def _create_distribution_variables(**kwargs):
        recorder.distribution_variable_kwargs = kwargs
        prefix = f"{kwargs['variable_namespace']}_{kwargs['environment']}_distribution"
        return tuple(
            types.SimpleNamespace(variable_name=f"{prefix}_{suffix}".upper())
            for suffix in ("base_url", "bucket", "cloudfront_id", "origin_id")
        )

    distribution_variables.create_distribution_variables = (
        _create_distribution_variables
    )

    return {
        "webapp_vps_stack": vps,
        "webapp_database_stack": database,
        "webapp_api_stack": api,
        "webapp_distribution_github_variables": distribution_variables,
    }


def _environment_stack(monkeypatch, **arg_overrides):
    recorder = _Recorder()
    module = _load_template_module(
        monkeypatch,
        recorder,
        "webapp_environment_stack.py",
        extra_modules=_fake_sibling_modules(recorder),
    )
    kwargs = dict(
        deploy_namespace="yoke",
        environment="prod",
        stack_name="yoke-prod",
        domain_name="example.com",
        api_host="api.example.com",
        origin_host="origin.example.com",
        hosted_zone_id="Z123",
        api_origin_port=8100,
        vps_instance_type="t4g.medium",
        vps_root_volume_gb=40,
        vps_ssh_key_name="yoke-key",
        database_name="yoke_prod",
        database_master_username="yoke_admin",
        database_engine_version="16.13",
        database_min_capacity_acu=0.0,
        database_max_capacity_acu=4.0,
        database_backup_retention_days=7,
        database_allowed_security_group_ids=["sg-tenant-provisioner"],
    )
    kwargs.update(arg_overrides)
    stack = module.WebappEnvironmentStack(
        "yoke-prod",
        module.WebappEnvironmentArgs(**kwargs),
    )
    return recorder, stack


class TestEnvironmentOriginRuntimeSubstrate:
    def test_database_allows_origin_and_configured_service_groups(self, monkeypatch):
        recorder, _stack = _environment_stack(monkeypatch)
        database = recorder.single("database")
        assert database.args.allowed_security_group_ids == [
            "sg-fake",
            "sg-tenant-provisioner",
        ]

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

    def test_instance_profile_wired_into_vps(self, monkeypatch):
        recorder, _stack = _environment_stack(monkeypatch)
        profile = recorder.single("originInstanceProfile")
        assert profile.kwargs["role"].value == "originRole.name"
        vps = recorder.single("vps")
        assert vps.args.iam_instance_profile_name.value == (
            "originInstanceProfile.name"
        )

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

    def test_bucket_lifecycle_expires_artifacts(self, monkeypatch):
        recorder, _stack = _environment_stack(monkeypatch)
        lifecycle = recorder.single("artifactsBucketLifecycle")
        (rule,) = lifecycle.kwargs["rules"]
        assert rule.kwargs["id"] == "expire-artifacts"
        assert rule.kwargs["status"] == "Enabled"
        assert rule.kwargs["expiration"].kwargs["days"] == 365

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
            stack_name="yoke-stage",
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
        assert record.kwargs["records"] == ["198.51.100.7"]
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
