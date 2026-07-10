"""Tests for the webapp container-registry Pulumi template component.

Mirrors ``test_webapp_database_stack_rotation.py``'s harness mechanics: fake
``pulumi`` / ``pulumi_aws`` modules are injected into ``sys.modules`` and the
template module is loaded straight from ``templates/webapp/infra/``. The fake
resource classes record constructor kwargs so tests assert the declared AWS
surface without the Pulumi engine. The fakes are shared by
``test_webapp_environment_stack.py``.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

from runtime.api.domain.webapp_pulumi_test_support import (
    _FakeOutput,
    _make_certificate_class,
    _make_dynamic_module,
)


class _FakeArgs:
    """Recording stand-in for ``pulumi_aws`` ``*Args`` input classes."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.__dict__.update(kwargs)


class _FakeComponentResource:
    def __init__(self, type_, name, props=None, opts=None):
        self.component_type = type_
        self.component_name = name
        self.component_opts = opts
        self.registered_outputs = None

    def register_outputs(self, outputs):
        self.registered_outputs = outputs


class _FakeResourceOptions:
    def __init__(
        self, parent=None, ignore_changes=None, aliases=None, import_=None,
        depends_on=None, provider=None,
    ):
        self.parent = parent
        self.ignore_changes = ignore_changes
        self.aliases = aliases
        self.import_ = import_
        self.depends_on = depends_on
        self.provider = provider

    @staticmethod
    def merge(first, second):
        merged = _FakeResourceOptions()
        for source in (first, second):
            if source is None:
                continue
            if source.parent is not None:
                merged.parent = source.parent
            if source.ignore_changes:
                merged.ignore_changes = list(merged.ignore_changes or []) + list(
                    source.ignore_changes
                )
            if source.aliases:
                merged.aliases = list(merged.aliases or []) + list(source.aliases)
            if source.import_ is not None:
                merged.import_ = source.import_
            if source.depends_on:
                merged.depends_on = list(merged.depends_on or []) + list(
                    source.depends_on
                )
            if source.provider is not None:
                merged.provider = source.provider
        return merged


class _Recorder:
    """Collects every fake resource construction + ``pulumi.export`` call."""

    def __init__(self):
        self.resources = []
        self.exports = {}

    def single(self, resource_name):
        matches = [
            resource
            for resource in self.resources
            if resource.resource_name == resource_name
        ]
        assert len(matches) == 1, f"expected exactly one {resource_name!r}"
        return matches[0]


def _make_resource_class(recorder, type_name):
    class _Resource:
        def __init__(self, resource_name, opts=None, **kwargs):
            self.resource_type = type_name
            self.resource_name = resource_name
            self.opts = opts
            self.kwargs = kwargs
            recorder.resources.append(self)

        def __getattr__(self, item):
            kwargs = self.__dict__.get("kwargs") or {}
            if item in kwargs:
                return kwargs[item]
            name = self.__dict__.get("resource_name", "?")
            return _FakeOutput(f"{name}.{item}")

    _Resource.__name__ = type_name.rsplit(":", 1)[-1]
    return _Resource


def _build_fake_pulumi(recorder):
    fake = types.ModuleType("pulumi")
    fake.ComponentResource = _FakeComponentResource
    fake.ResourceOptions = _FakeResourceOptions
    fake.Alias = _FakeArgs
    fake.Input = object
    fake.Output = _FakeOutput
    fake.RunError = RuntimeError
    fake.AssetArchive = lambda assets: _FakeArgs(assets=assets)
    fake.StringAsset = lambda text: _FakeArgs(text=text)
    fake.export = lambda key, value: recorder.exports.__setitem__(key, value)
    fake.dynamic = _make_dynamic_module(recorder)
    return fake


def _build_fake_aws(recorder):
    aws = types.ModuleType("pulumi_aws")
    aws.get_caller_identity = (
        lambda: types.SimpleNamespace(account_id="123456789012")
    )
    aws.get_region = lambda: types.SimpleNamespace(name="us-east-1")
    aws.ec2 = types.SimpleNamespace(
        get_vpc=lambda default=True: types.SimpleNamespace(id="vpc-fake"),
        get_subnets=lambda filters=None: types.SimpleNamespace(
            ids=["subnet-a", "subnet-b"],
        ),
        GetSubnetsFilterArgs=_FakeArgs,
        Vpc=_make_resource_class(recorder, "aws:ec2:Vpc"),
        InternetGateway=_make_resource_class(
            recorder, "aws:ec2:InternetGateway",
        ),
        Subnet=_make_resource_class(recorder, "aws:ec2:Subnet"),
        RouteTable=_make_resource_class(recorder, "aws:ec2:RouteTable"),
        Route=_make_resource_class(recorder, "aws:ec2:Route"),
        RouteTableAssociation=_make_resource_class(
            recorder, "aws:ec2:RouteTableAssociation",
        ),
        SecurityGroup=_make_resource_class(recorder, "aws:ec2:SecurityGroup"),
        SecurityGroupIngressArgs=_FakeArgs,
        SecurityGroupEgressArgs=_FakeArgs,
        Instance=_make_resource_class(recorder, "aws:ec2:Instance"),
        InstanceRootBlockDeviceArgs=_FakeArgs,
        Eip=_make_resource_class(recorder, "aws:ec2:Eip"),
        LaunchTemplate=_make_resource_class(recorder, "aws:ec2:LaunchTemplate"),
        LaunchTemplateIamInstanceProfileArgs=_FakeArgs,
        LaunchTemplateBlockDeviceMappingArgs=_FakeArgs,
        LaunchTemplateBlockDeviceMappingEbsArgs=_FakeArgs,
        LaunchTemplateTagSpecificationArgs=_FakeArgs,
    )
    aws.ssm = types.SimpleNamespace(
        get_parameter=lambda name: types.SimpleNamespace(value="ami-fake1234"),
        Parameter=_make_resource_class(recorder, "aws:ssm:Parameter"),
    )
    aws.ecr = types.SimpleNamespace(
        Repository=_make_resource_class(recorder, "aws:ecr:Repository"),
        RepositoryImageScanningConfigurationArgs=_FakeArgs,
        LifecyclePolicy=_make_resource_class(recorder, "aws:ecr:LifecyclePolicy"),
    )
    aws.cloudwatch = types.SimpleNamespace(
        LogGroup=_make_resource_class(recorder, "aws:cloudwatch:LogGroup"),
        EventRule=_make_resource_class(recorder, "aws:cloudwatch:EventRule"),
        EventTarget=_make_resource_class(recorder, "aws:cloudwatch:EventTarget"),
    )
    aws.cloudfront = types.SimpleNamespace(
        Distribution=_make_resource_class(
            recorder, "aws:cloudfront:Distribution",
        ),
        Function=_make_resource_class(recorder, "aws:cloudfront:Function"),
        OriginAccessControl=_make_resource_class(
            recorder, "aws:cloudfront:OriginAccessControl",
        ),
        OriginAccessIdentity=_make_resource_class(
            recorder, "aws:cloudfront:OriginAccessIdentity",
        ),
        DistributionOriginArgs=_FakeArgs,
        DistributionOriginS3OriginConfigArgs=_FakeArgs,
        DistributionOriginCustomOriginConfigArgs=_FakeArgs,
        DistributionOriginCustomHeaderArgs=_FakeArgs,
        DistributionDefaultCacheBehaviorArgs=_FakeArgs,
        DistributionOrderedCacheBehaviorArgs=_FakeArgs,
        DistributionDefaultCacheBehaviorFunctionAssociationArgs=_FakeArgs, DistributionOrderedCacheBehaviorFunctionAssociationArgs=_FakeArgs,
        DistributionViewerCertificateArgs=_FakeArgs,
        DistributionRestrictionsArgs=_FakeArgs,
        DistributionRestrictionsGeoRestrictionArgs=_FakeArgs,
    )
    aws.iam = types.SimpleNamespace(
        Role=_make_resource_class(recorder, "aws:iam:Role"),
        RolePolicy=_make_resource_class(recorder, "aws:iam:RolePolicy"),
        RolePolicyAttachment=_make_resource_class(
            recorder, "aws:iam:RolePolicyAttachment",
        ),
        InstanceProfile=_make_resource_class(recorder, "aws:iam:InstanceProfile"),
    )
    aws.autoscaling = types.SimpleNamespace(
        Group=_make_resource_class(recorder, "aws:autoscaling:Group"),
        GroupLaunchTemplateArgs=_FakeArgs,
        GroupTagArgs=_FakeArgs,
    )
    aws.lambda_ = types.SimpleNamespace(
        Function=_make_resource_class(recorder, "aws:lambda:Function"),
        FunctionEnvironmentArgs=_FakeArgs,
        FunctionUrl=_make_resource_class(recorder, "aws:lambda:FunctionUrl"),
        Permission=_make_resource_class(recorder, "aws:lambda:Permission"),
    )
    aws.route53 = types.SimpleNamespace(
        get_zone=lambda zone_id: types.SimpleNamespace(zone_id=zone_id),
        Record=_make_resource_class(recorder, "aws:route53:Record"),
        RecordAliasArgs=_FakeArgs,
    )
    aws.acm = types.SimpleNamespace(
        Certificate=_make_certificate_class(recorder),
        CertificateValidation=_make_resource_class(
            recorder, "aws:acm:CertificateValidation",
        ),
        get_certificate=lambda **kwargs: types.SimpleNamespace(
            arn="arn:aws:acm:us-east-1:123456789012:certificate/abc",
        ),
    )
    aws.s3 = types.SimpleNamespace(
        BucketV2=_make_resource_class(recorder, "aws:s3:BucketV2"),
        BucketPublicAccessBlock=_make_resource_class(
            recorder, "aws:s3:BucketPublicAccessBlock",
        ),
        BucketLifecycleConfigurationV2=_make_resource_class(
            recorder, "aws:s3:BucketLifecycleConfigurationV2",
        ),
        BucketPolicy=_make_resource_class(recorder, "aws:s3:BucketPolicy"),
        BucketLifecycleConfigurationV2RuleArgs=_FakeArgs,
        BucketLifecycleConfigurationV2RuleExpirationArgs=_FakeArgs,
    )
    return aws


def _load_template_module(monkeypatch, recorder, filename, extra_modules=None):
    fake_pulumi = _build_fake_pulumi(recorder)
    monkeypatch.setitem(sys.modules, "pulumi", fake_pulumi)
    monkeypatch.setitem(sys.modules, "pulumi.dynamic", fake_pulumi.dynamic)
    monkeypatch.setitem(sys.modules, "pulumi_aws", _build_fake_aws(recorder))
    for name, module in (extra_modules or {}).items():
        monkeypatch.setitem(sys.modules, name, module)
    repo_root = Path(__file__).resolve().parents[3]
    path = repo_root / "templates" / "webapp" / "infra" / filename
    module_name = f"_{filename[:-3]}_under_test"
    spec = importlib.util.spec_from_file_location(module_name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


def _registry_stack(monkeypatch, repository_name="yoke-core"):
    recorder = _Recorder()
    module = _load_template_module(
        monkeypatch, recorder, "webapp_registry_stack.py",
    )
    stack = module.WebappRegistryStack(
        "yoke-registry",
        module.WebappRegistryArgs(
            deploy_namespace="yoke", repository_name=repository_name,
        ),
    )
    return recorder, stack


def test_repository_declares_scan_push_mutability_and_force_delete(monkeypatch):
    recorder, _stack = _registry_stack(monkeypatch)
    repo = recorder.single("containerRepository")
    assert repo.kwargs["name"] == "yoke-core"
    assert repo.kwargs["image_tag_mutability"] == "MUTABLE"
    assert repo.kwargs["force_delete"] is True
    scanning = repo.kwargs["image_scanning_configuration"]
    assert scanning.kwargs == {"scan_on_push": True}
    assert repo.kwargs["tags"] == {"project": "yoke"}


def test_lifecycle_policy_expires_untagged_and_caps_tagged_history(monkeypatch):
    recorder, _stack = _registry_stack(monkeypatch)
    lifecycle = recorder.single("containerRepositoryLifecycle")
    assert lifecycle.kwargs["repository"] == "yoke-core"
    rules = json.loads(lifecycle.kwargs["policy"])["rules"]
    assert [rule["rulePriority"] for rule in rules] == [1, 2]
    untagged, tagged = rules
    assert untagged["selection"]["tagStatus"] == "untagged"
    assert untagged["action"] == {"type": "expire"}
    assert tagged["selection"]["tagStatus"] == "tagged"
    assert tagged["selection"]["countType"] == "imageCountMoreThan"
    assert tagged["selection"]["countNumber"] == 20
    assert tagged["action"] == {"type": "expire"}


def test_outputs_exported_and_registered(monkeypatch):
    recorder, stack = _registry_stack(monkeypatch)
    expected = {
        "containerRepositoryUrl",
        "containerRepositoryName",
        "containerRegistryId",
    }
    assert set(recorder.exports) == expected
    assert set(stack.registered_outputs) == expected
    assert recorder.exports["containerRepositoryName"] == "yoke-core"
    assert stack.component_type == "webapp:infra:WebappRegistryStack"
