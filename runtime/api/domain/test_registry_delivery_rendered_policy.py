"""The policy a real adopter's settings render to, end to end.

Every earlier defect in this grant shipped past tests that each exercised one
layer: the renderer merged what the environments stated, the Pack module shaped
the statements, and the Sids and action sets were as expected, while the
resource a statement would actually be evaluated against was never asserted.
This file renders one realistic project — two environments, each stating its
own delivery facts beside unrelated settings — through the engine renderer and
the latest Pack's policy, the way the stack config template and the Pulumi
entrypoint carry it, and pins the rendered resources literally.
"""

from __future__ import annotations

import json

import pytest

from runtime.api.domain.registry_delivery_authority_test_support import (
    environment,
    load_pack_module,
    settings_for,
)

from yoke_core.domain import project_renderer_pulumi_ci as renderer

policy = load_pack_module("webapp_registry_delivery_ssm_policy")
ci_policy = load_pack_module("webapp_registry_ci_policy")

REGION = "us-east-1"
ACCOUNT = "123456789012"

#: Two environments of one project, each stating its own origin box, artifact
#: bucket, and key prefix beside settings the renderer reads for other
#: purposes. The documents differ in ownership on purpose.
STAGE = environment(
    "stage",
    {
        "distribution": {"bucket_name": "example-stage-web"},
        "delivery_authority": {
            "instance_tags": {"Name": "example-stage-origin"},
            "documents": ["AWS-RunShellScript"],
            "artifact_buckets": ["example-stage-artifacts"],
            "artifact_key_prefixes": ["ci-deploy/"],
        },
    },
)
PROD = environment(
    "prod",
    {
        "distribution": {"bucket_name": "example-prod-web"},
        "github_app": {
            "private_key_secret_arn": (
                f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:example-app-key"
            )
        },
        "delivery_authority": {
            "instance_tags": {"Name": "example-prod-origin"},
            "documents": ["AWS-RunShellScript", "example-prepare-box"],
            "artifact_buckets": ["example-prod-artifacts"],
            "artifact_key_prefixes": ["ci-deploy/"],
        },
    },
)


@pytest.fixture(scope="module")
def rendered() -> list[dict]:
    values = renderer.delivery_ci_values(settings_for(STAGE, PROD))
    # The stack config template carries each rendered value verbatim, and the
    # Pulumi entrypoint hands the parsed descriptor to the Pack's policy.
    grant = policy.delivery_authority_from_config(
        json.loads(values["delivery_authority_json"])
    )
    document = ci_policy.delivery_policy_json(
        region=REGION,
        account_id=ACCOUNT,
        deploy_namespace="example",
        state_bucket="example-state",
        kms_key_arn=f"arn:aws:kms:{REGION}:{ACCOUNT}:key/abc",
        distribution_bucket_names=json.loads(
            values["delivery_distribution_bucket_names_json"]
        ),
        cloudfront_distribution_ids=json.loads(
            values["delivery_cloudfront_distribution_ids_json"]
        ),
        github_app_private_key_secret_arns=json.loads(
            values["github_app_private_key_secret_arns_json"]
        ),
        delivery_authority=grant,
    )
    return json.loads(document)["Statement"]


def _by_sid(statements: list[dict], sid: str) -> dict:
    return next(s for s in statements if s["Sid"] == sid)


class TestTheRenderedGrantNamesWhatTheServiceEvaluates:
    def test_each_document_carries_the_account_its_owner_has(self, rendered) -> None:
        assert _by_sid(rendered, "RunDeliveryDocuments")["Resource"] == [
            "arn:aws:ssm:us-east-1::document/AWS-RunShellScript",
            "arn:aws:ssm:us-east-1:123456789012:document/example-prepare-box",
        ]

    def test_send_command_reaches_both_environments_origin_boxes(
        self, rendered
    ) -> None:
        statement = _by_sid(rendered, "RunDeliveryDocumentsOnProjectInstances")
        assert statement["Resource"] == "arn:aws:ec2:us-east-1:123456789012:instance/*"
        assert statement["Condition"]["StringEquals"] == {
            "ssm:resourceTag/Name": ["example-prod-origin", "example-stage-origin"],
        }

    def test_artifacts_move_only_under_the_stated_prefix_in_each_bucket(
        self, rendered
    ) -> None:
        assert _by_sid(rendered, "TransferDeliveryArtifacts")["Resource"] == [
            "arn:aws:s3:::example-prod-artifacts/ci-deploy/*",
            "arn:aws:s3:::example-stage-artifacts/ci-deploy/*",
        ]
        listing = _by_sid(rendered, "ListDeliveryArtifactPrefixes")
        assert listing["Resource"] == [
            "arn:aws:s3:::example-prod-artifacts",
            "arn:aws:s3:::example-stage-artifacts",
        ]
        assert listing["Condition"]["StringLike"]["s3:prefix"] == ["ci-deploy/*"]

    def test_the_grant_joins_the_delivery_policy_rather_than_replacing_it(
        self, rendered
    ) -> None:
        # The opt-in statements extend the policy the role already had: image
        # publishing and distribution statements are still there, and the
        # App-key deny still closes the document.
        sids = [s["Sid"] for s in rendered]
        assert sids.index("ProjectImageDelivery") < sids.index("RunDeliveryDocuments")
        assert sids[-1] == "DenyGitHubAppPrivateKeys"
        assert _by_sid(rendered, "PublishDistributionArtifacts")["Resource"] == [
            "arn:aws:s3:::example-prod-web/*",
            "arn:aws:s3:::example-stage-web/*",
        ]
