"""The delivery role's opt-in grant is bounded by what a project stated.

A role that can run a command on an instance can run anything that instance's
own role permits, so the tests that matter here are the ones asserting what the
grant does NOT reach: no statement at all when nothing is stated, an exact
resource when something is, and a refusal — never a wider grant — when the
statement is incomplete. How several environments merge into one descriptor is
covered beside this file, in the merge tests.
"""

from __future__ import annotations

import pytest

from runtime.api.domain.registry_delivery_authority_test_support import (
    ACCOUNT,
    PACK_INFRA,
    REGION,
    STATED,
    load_pack_module,
)

policy = load_pack_module("webapp_registry_delivery_ssm_policy")


class TestNothingStatedGrantsNothing:
    def test_an_empty_grant_emits_no_statements(self) -> None:
        assert policy.DeliveryAuthority().statements(
            region=REGION, account_id=ACCOUNT
        ) == []

    def test_an_empty_grant_knows_it_is_empty(self) -> None:
        assert policy.DeliveryAuthority().is_empty
        assert policy.delivery_authority_from_config(None).is_empty

    def test_an_empty_descriptor_round_trips_to_an_empty_grant(self) -> None:
        assert policy.delivery_authority_from_config({}).is_empty


class TestExactResourceScoping:
    def _statements(self) -> list[dict]:
        return policy.delivery_authority_from_config(STATED).statements(
            region=REGION, account_id=ACCOUNT
        )

    def _by_sid(self, sid: str) -> dict:
        return next(s for s in self._statements() if s["Sid"] == sid)

    def test_send_command_is_bound_to_the_stated_instance_tags(self) -> None:
        statement = self._by_sid("RunDeliveryDocumentsOnProjectInstances")
        assert statement["Resource"] == f"arn:aws:ec2:{REGION}:{ACCOUNT}:instance/*"
        assert statement["Condition"]["StringEquals"] == {
            "ssm:resourceTag/project": ["example"],
            "ssm:resourceTag/role": ["origin"],
        }

    def test_the_instance_condition_uses_the_documented_ssm_key(self) -> None:
        # The grant rests on this condition matching, so it follows the
        # service-specific key Run Command documents for tag-bounded
        # SendCommand rather than the global ``aws:ResourceTag`` one.
        condition = self._by_sid("RunDeliveryDocumentsOnProjectInstances")["Condition"]
        assert all(
            key.startswith("ssm:resourceTag/") for key in condition["StringEquals"]
        )

    def test_send_command_names_the_stated_documents_and_nothing_else(self) -> None:
        assert self._by_sid("RunDeliveryDocuments")["Resource"] == [
            f"arn:aws:ssm:{REGION}:{ACCOUNT}:document/AWS-RunShellScript"
        ]

    def test_artifact_access_is_bound_to_the_stated_prefixes(self) -> None:
        transfer = self._by_sid("TransferDeliveryArtifacts")
        assert transfer["Resource"] == ["arn:aws:s3:::example-artifacts/releases/*"]
        listing = self._by_sid("ListDeliveryArtifactPrefixes")
        assert listing["Resource"] == ["arn:aws:s3:::example-artifacts"]
        assert listing["Condition"]["StringLike"]["s3:prefix"] == ["releases/*"]

    def test_no_statement_reaches_every_resource_except_the_read_backs(self) -> None:
        # ``*`` is defensible only for the invocation reads, which carry no
        # resource of their own; anywhere else it would undo the bounds above.
        wildcards = [s["Sid"] for s in self._statements() if s["Resource"] == "*"]
        assert wildcards == ["ReadDeliveryCommandResults"]


class TestSeveralInstancesAndBuckets:
    """A role serving several environments reaches each of them, and no more."""

    STATED_SET = {
        "instance_tags": {"Name": ["stage-origin", "prod-origin"]},
        "documents": ["AWS-RunShellScript"],
        "artifact_buckets": ["example-prod", "example-stage"],
        "artifact_key_prefixes": ["ci-deploy/"],
    }

    def _statements(self) -> list[dict]:
        return policy.delivery_authority_from_config(self.STATED_SET).statements(
            region=REGION, account_id=ACCOUNT
        )

    def _by_sid(self, sid: str) -> dict:
        return next(s for s in self._statements() if s["Sid"] == sid)

    def test_one_tag_key_may_accept_any_of_several_values(self) -> None:
        statement = self._by_sid("RunDeliveryDocumentsOnProjectInstances")
        assert statement["Condition"]["StringEquals"] == {
            "ssm:resourceTag/Name": ["prod-origin", "stage-origin"],
        }

    def test_every_prefix_is_scoped_across_every_bucket(self) -> None:
        assert self._by_sid("TransferDeliveryArtifacts")["Resource"] == [
            "arn:aws:s3:::example-prod/ci-deploy/*",
            "arn:aws:s3:::example-stage/ci-deploy/*",
        ]

    def test_listing_covers_every_bucket_under_the_same_prefix_bound(self) -> None:
        listing = self._by_sid("ListDeliveryArtifactPrefixes")
        assert listing["Resource"] == [
            "arn:aws:s3:::example-prod",
            "arn:aws:s3:::example-stage",
        ]
        assert listing["Condition"]["StringLike"]["s3:prefix"] == ["ci-deploy/*"]

    def test_no_statement_reaches_a_whole_stated_bucket(self) -> None:
        for statement in self._statements():
            resources = statement["Resource"]
            resources = [resources] if isinstance(resources, str) else resources
            assert "arn:aws:s3:::example-prod/*" not in resources
            assert "arn:aws:s3:::example-stage/*" not in resources


class TestPartialStatementsAreRefused:
    @pytest.mark.parametrize(
        "stated",
        [
            {"documents": ["AWS-RunShellScript"]},
            {"instance_tags": {"project": "example"}},
            {"artifact_buckets": ["example-artifacts"]},
            {"artifact_key_prefixes": ["releases/"]},
        ],
        ids=["documents-only", "tags-only", "buckets-only", "prefixes-only"],
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
            {"artifact_buckets": "example-artifacts"},
            {"artifact_key_prefixes": "releases/"},
            {"instance_tags": {"project": ""}},
            {"instance_tags": {"project": []}},
            {"instance_tags": {"project": [1]}},
            {"unexpected": True},
        ],
        ids=[
            "tags-not-a-mapping",
            "documents-not-a-list",
            "buckets-not-a-list",
            "prefixes-not-a-list",
            "empty-tag-value",
            "empty-tag-value-list",
            "non-string-tag-value",
            "unknown-key",
        ],
    )
    def test_a_malformed_descriptor_raises(self, stated: dict) -> None:
        with pytest.raises(policy.SsmDeliveryConfigError):
            policy.delivery_authority_from_config(stated)

    def test_a_scalar_where_a_descriptor_belongs_raises(self) -> None:
        with pytest.raises(policy.SsmDeliveryConfigError):
            policy.delivery_authority_from_config("yes")


class TestUnchangedAuthorityForNonOptingProjects:
    def test_the_delivery_policy_is_byte_identical_without_a_grant(self) -> None:
        released = load_pack_module(
            "released_ci_policy",
            PACK_INFRA.parents[2] / "1.1.0" / "files" / "infra"
            / "webapp_registry_ci_policy.py",
        )
        current = load_pack_module("webapp_registry_ci_policy")
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
