"""The delivery role's opt-in grant is bounded by what a project stated.

A role that can run a command on an instance can run anything that instance's
own role permits, so the tests that matter here are the ones asserting what the
grant does NOT reach: no statement at all when nothing is stated, an exact
resource when something is, and a refusal — never a wider grant — when the
statement is incomplete.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from yoke_core.domain import project_renderer_pulumi_ci as renderer
from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)

PACK_INFRA = (
    Path(__file__).resolve().parents[3]
    / "packs"
    / "registry-oidc"
    / "versions"
    / "1.2.0"
    / "files"
    / "infra"
)
REGION = "us-east-1"
ACCOUNT = "123456789012"


def _load(module_name: str, path: Path | None = None):
    """Import one Pack file by path; Pack source is not on sys.path.

    Registered in ``sys.modules`` before execution because ``dataclasses``
    resolves a class's own module while processing it, and a module that is
    not yet registered resolves to ``None``.
    """
    spec = importlib.util.spec_from_file_location(
        module_name, path or PACK_INFRA / f"{module_name}.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


policy = _load("webapp_registry_delivery_ssm_policy")


def _environment(name: str, settings: dict) -> RendererEnvironmentSettings:
    return RendererEnvironmentSettings(id=name, name=name, settings=settings)


def _settings(*environments: RendererEnvironmentSettings) -> ProjectRendererSettings:
    return ProjectRendererSettings(
        project="example",
        deploy_namespace="example",
        display_name="Example",
        site_id="1",
        site_settings={},
        primary_environment=environments[0] if environments else None,
        environments=tuple(environments),
        capabilities={},
    )


STATED = {
    "instance_tags": {"project": "example", "role": "origin"},
    "documents": ["AWS-RunShellScript"],
    "artifact_bucket": "example-artifacts",
    "artifact_key_prefixes": ["releases/"],
}


class TestNothingStatedGrantsNothing:
    def test_an_empty_grant_emits_no_statements(self) -> None:
        assert policy.DeliveryAuthority().statements(
            region=REGION, account_id=ACCOUNT
        ) == []

    def test_an_empty_grant_knows_it_is_empty(self) -> None:
        assert policy.DeliveryAuthority().is_empty
        assert policy.delivery_authority_from_config(None).is_empty

    def test_a_project_that_states_nothing_renders_an_empty_descriptor(self) -> None:
        values = renderer.delivery_ci_values(
            _settings(_environment("prod", {"distribution": {"bucket_name": "b"}}))
        )
        assert json.loads(values["delivery_authority_json"]) == {}

    def test_an_empty_descriptor_round_trips_to_an_empty_grant(self) -> None:
        assert policy.delivery_authority_from_config({}).is_empty


class TestExactResourceScoping:
    def _statements(self) -> list[dict]:
        return policy.delivery_authority_from_config(STATED).statements(
            region=REGION, account_id=ACCOUNT
        )

    def test_send_command_is_bound_to_the_stated_instance_tags(self) -> None:
        statement = next(
            s
            for s in self._statements()
            if s["Sid"] == "RunDeliveryDocumentsOnProjectInstances"
        )
        assert statement["Resource"] == f"arn:aws:ec2:{REGION}:{ACCOUNT}:instance/*"
        assert statement["Condition"]["StringEquals"] == {
            "aws:ResourceTag/project": "example",
            "aws:ResourceTag/role": "origin",
        }

    def test_send_command_names_the_stated_documents_and_nothing_else(self) -> None:
        statement = next(
            s for s in self._statements() if s["Sid"] == "RunDeliveryDocuments"
        )
        assert statement["Resource"] == [
            f"arn:aws:ssm:{REGION}:{ACCOUNT}:document/AWS-RunShellScript"
        ]

    def test_artifact_access_is_bound_to_the_stated_prefixes(self) -> None:
        transfer = next(
            s for s in self._statements() if s["Sid"] == "TransferDeliveryArtifacts"
        )
        assert transfer["Resource"] == ["arn:aws:s3:::example-artifacts/releases/*"]
        listing = next(
            s for s in self._statements() if s["Sid"] == "ListDeliveryArtifactPrefixes"
        )
        assert listing["Resource"] == "arn:aws:s3:::example-artifacts"
        assert listing["Condition"]["StringLike"]["s3:prefix"] == ["releases/*"]

    def test_no_statement_reaches_every_resource_except_the_read_backs(self) -> None:
        # ``*`` is defensible only for the invocation reads, which carry no
        # resource of their own; anywhere else it would undo the bounds above.
        wildcards = [s["Sid"] for s in self._statements() if s["Resource"] == "*"]
        assert wildcards == ["ReadDeliveryCommandResults"]


class TestPartialStatementsAreRefused:
    @pytest.mark.parametrize(
        "stated",
        [
            {"documents": ["AWS-RunShellScript"]},
            {"instance_tags": {"project": "example"}},
            {"artifact_bucket": "example-artifacts"},
            {"artifact_key_prefixes": ["releases/"]},
        ],
        ids=["documents-only", "tags-only", "bucket-only", "prefixes-only"],
    )
    def test_half_a_bound_is_an_error_not_a_wider_grant(self, stated: dict) -> None:
        grant = policy.delivery_authority_from_config(stated)
        with pytest.raises(policy.SsmDeliveryConfigError):
            grant.statements(region=REGION, account_id=ACCOUNT)


class TestMalformedStatementsAreRefused:
    @pytest.mark.parametrize(
        "stated",
        [
            {"instance_tags": ["project=example"]},
            {"documents": "AWS-RunShellScript"},
            {"artifact_bucket": ["example-artifacts"]},
            {"artifact_key_prefixes": "releases/"},
            {"instance_tags": {"project": ""}},
            {"unexpected": True},
        ],
        ids=[
            "tags-not-a-mapping",
            "documents-not-a-list",
            "bucket-not-a-string",
            "prefixes-not-a-list",
            "empty-tag-value",
            "unknown-key",
        ],
    )
    def test_a_malformed_descriptor_raises(self, stated: dict) -> None:
        with pytest.raises(policy.SsmDeliveryConfigError):
            policy.delivery_authority_from_config(stated)

    def test_a_scalar_where_a_descriptor_belongs_raises(self) -> None:
        with pytest.raises(policy.SsmDeliveryConfigError):
            policy.delivery_authority_from_config("yes")


class TestMultipleEnvironments:
    def test_grants_from_every_environment_are_merged(self) -> None:
        values = renderer.delivery_ci_values(
            _settings(
                _environment(
                    "stage",
                    {
                        "delivery_authority": {
                            "instance_tags": {"project": "example"},
                            "documents": ["AWS-RunShellScript"],
                            "artifact_bucket": "example-artifacts",
                            "artifact_key_prefixes": ["stage/"],
                        }
                    },
                ),
                _environment(
                    "prod",
                    {
                        "delivery_authority": {
                            "instance_tags": {"role": "origin"},
                            "documents": ["AWS-RunPowerShellScript"],
                            "artifact_bucket": "example-artifacts",
                            "artifact_key_prefixes": ["prod/"],
                        }
                    },
                ),
            )
        )
        assert json.loads(values["delivery_authority_json"]) == {
            "instance_tags": {"project": "example", "role": "origin"},
            "documents": ["AWS-RunPowerShellScript", "AWS-RunShellScript"],
            "artifact_bucket": "example-artifacts",
            "artifact_key_prefixes": ["prod/", "stage/"],
        }

    def test_an_environment_that_states_nothing_contributes_nothing(self) -> None:
        values = renderer.delivery_ci_values(
            _settings(
                _environment("stage", {}),
                _environment("prod", {"delivery_authority": STATED}),
            )
        )
        assert json.loads(values["delivery_authority_json"]) == {
            "instance_tags": {"project": "example", "role": "origin"},
            "documents": ["AWS-RunShellScript"],
            "artifact_bucket": "example-artifacts",
            "artifact_key_prefixes": ["releases/"],
        }

    def test_disagreeing_artifact_buckets_are_refused(self) -> None:
        with pytest.raises(ValueError, match="different artifact_bucket"):
            renderer.delivery_ci_values(
                _settings(
                    _environment(
                        "stage", {"delivery_authority": {"artifact_bucket": "one"}}
                    ),
                    _environment(
                        "prod", {"delivery_authority": {"artifact_bucket": "two"}}
                    ),
                )
            )

    def test_an_unknown_environment_key_is_refused(self) -> None:
        with pytest.raises(ValueError, match="unknown delivery_authority keys"):
            renderer.delivery_ci_values(
                _settings(
                    _environment("prod", {"delivery_authority": {"bucket": "one"}})
                )
            )


class TestUnchangedAuthorityForNonOptingProjects:
    def test_the_delivery_policy_is_byte_identical_without_a_grant(self) -> None:
        released = _load_released_policy()
        current = _load("webapp_registry_ci_policy")
        common = dict(
            region=REGION,
            account_id=ACCOUNT,
            deploy_namespace="example",
            state_bucket="example-state",
            kms_key_arn=f"arn:aws:kms:{REGION}:{ACCOUNT}:key/abc",
            distribution_bucket_names=["example-web"],
            cloudfront_distribution_ids=["E123"],
            github_app_private_key_secret_arns=[],
        )
        assert current.delivery_policy_json(**common) == released.delivery_policy_json(
            **common
        )


def _load_released_policy():
    """The previous released version, as the baseline a non-opting project keeps."""
    return _load(
        "released_ci_policy",
        PACK_INFRA.parents[2] / "1.1.0" / "files" / "infra"
        / "webapp_registry_ci_policy.py",
    )
