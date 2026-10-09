"""Exact promotion identity refuses missing, mismatched or fabricated proof."""

from copy import deepcopy
import json

import pytest

from runtime.api.fixtures.hosted_promotion import envelope, payload
from yoke_core.domain.hosted_promotion_receipt import (
    PromotionReceiptRefused,
    validate_promotion_receipt,
)
from yoke_core.domain.deployment_run_project_sources import delivered_source_sha


def test_successful_noop_retains_exact_deployed_sha():
    receipt = envelope(payload(pin_pushed=False))
    assert (
        validate_promotion_receipt(receipt, environment="stage", product_sha="a" * 40)
        == receipt["payload"]
    )


@pytest.mark.parametrize(
    "receipt,key,value,reason",
    [
        ("payload", "platform_sha", "b" * 12, "promotion_receipt_sha_invalid"),
        ("payload", "product_sha", "c" * 40, "promotion_receipt_identity_mismatch"),
        (
            "payload",
            "target_environment",
            "prod",
            "promotion_receipt_identity_mismatch",
        ),
        ("payload", "pin_pushed", "false", "promotion_receipt_run_invalid"),
        ("payload", "run_id", "999", "promotion_receipt_provenance_mismatch"),
        ("payload", "run_attempt", 2, "promotion_receipt_provenance_mismatch"),
        ("payload", "proven_consumer_sha", "", "promotion_receipt_consumer_unproven"),
        (
            "envelope",
            "display_title",
            "another dispatch",
            "promotion_receipt_provenance_mismatch",
        ),
        (
            "envelope",
            "artifact_name",
            "another artifact",
            "promotion_receipt_provenance_mismatch",
        ),
        (
            "envelope",
            "workflow_path",
            ".github/workflows/another.yml",
            "promotion_receipt_provenance_mismatch",
        ),
    ],
)
def test_mismatched_receipt_refuses(receipt, key, value, reason):
    proof = deepcopy(envelope())
    target = proof["payload"] if receipt == "payload" else proof
    target[key] = value
    with pytest.raises(PromotionReceiptRefused) as error:
        validate_promotion_receipt(proof, environment="stage", product_sha="a" * 40)
    assert error.value.reason == reason
    assert "do not redeploy" in str(error.value)


def test_missing_receipt_and_wrong_explicit_commit_refuse():
    with pytest.raises(PromotionReceiptRefused, match="promotion_receipt_missing"):
        validate_promotion_receipt(None, environment="stage", product_sha="a" * 40)
    with pytest.raises(
        PromotionReceiptRefused, match="promotion_receipt_commit_mismatch"
    ):
        validate_promotion_receipt(
            envelope(), environment="stage", product_sha="a" * 40, commit_sha="e" * 40
        )


def test_hosted_missing_output_refuses_before_qa_while_generic_binding_is_unchanged():
    sources = {
        "projects": [{"project": "carried", "project_id": 2, "commit_sha": "c" * 40}]
    }
    run = {"project_id": 1, "release_lineage": "a" * 40, "bound_sources": sources}
    assert delivered_source_sha(run, 2) == "c" * 40
    run["stages"] = json.dumps(
        [
            {
                "workflow": "platform-release-bridge.yml",
                "input_bindings": {
                    "consumer_sha": {"project": "carried", "branch": "main"},
                },
            }
        ]
    )
    with pytest.raises(
        PromotionReceiptRefused, match="promotion_delivery_identity_missing"
    ):
        delivered_source_sha(run, 2)
    sources["projects"][0]["outputs"] = [{"commit_sha": "d" * 40, "reason": "pin"}]
    with pytest.raises(
        PromotionReceiptRefused, match="promotion_delivery_identity_missing"
    ):
        delivered_source_sha(run, 2)
    sources["projects"][0]["promotion_receipts"] = [envelope(payload(pin_pushed=False))]
    assert delivered_source_sha(run, 2) == "b" * 40
