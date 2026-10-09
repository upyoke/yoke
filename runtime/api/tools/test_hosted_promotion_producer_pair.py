"""Build actual companion receipts against the exact committed consumer."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from runtime.api.fixtures.hosted_promotion import envelope
from yoke_core.domain.hosted_promotion_receipt import (
    PromotionReceiptRefused,
    validate_promotion_receipt,
)


@pytest.fixture
def producer_root():
    root = os.environ.get("YOKE_PROMOTION_PRODUCER_ROOT")
    sha = os.environ.get("YOKE_PROMOTION_PRODUCER_SHA")
    if not root and not sha:
        pytest.skip(
            "exact companion proof is run separately with its named checkout and SHA"
        )
    assert root and sha, "both producer checkout and exact SHA are required"
    path = Path(root)

    def head():
        return subprocess.run(
            ["git", "-C", str(path), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()

    assert head() == sha, "producer candidate moved before pair proof"
    yield path
    assert head() == sha, "producer candidate moved during pair proof"


@pytest.mark.parametrize(
    "target,pushed,attempt",
    [
        ("stage", True, 1),
        ("prod", True, 1),
        ("stage", False, 1),
        ("prod", False, 1),
        ("stage", True, 2),
        ("prod", True, 2),
    ],
)
def test_actual_producer_receipt_matches_consumer_contract(
    producer_root, target, pushed, attempt
):
    environment = {
        "GITHUB_REPOSITORY": "upyoke/platform",
        "GITHUB_RUN_ID": "123",
        "GITHUB_RUN_ATTEMPT": str(attempt),
        "DEPLOY_ENVIRONMENT_RESULT": "success",
        "DISPATCH_ID": "yd-" + "d" * 32,
        "TARGET_ENVIRONMENT": target,
        "VERSION": f"0.1.1+launch.{461}",
        "PRODUCT_SHA": "a" * 40,
        "PLATFORM_SHA": ("b" if target == "stage" else "f") * 40,
        "PROVEN_CONSUMER_SHA": "c" * 40,
        "PIN_PUSHED": str(pushed).lower(),
    }
    completed = subprocess.run(
        [
            sys.executable,
            "-B",
            "-c",
            "import json,sys; from ops.promotion_receipt import build_receipt; print(json.dumps(build_receipt(json.load(sys.stdin))))",
        ],
        input=json.dumps(environment),
        capture_output=True,
        text=True,
        check=True,
        cwd=producer_root,
    )
    proof = envelope(json.loads(completed.stdout))
    assert (
        validate_promotion_receipt(proof, environment=target, product_sha="a" * 40)[
            "platform_sha"
        ]
        == environment["PLATFORM_SHA"]
    )
    wrong = "prod" if target == "stage" else "stage"
    with pytest.raises(
        PromotionReceiptRefused, match="promotion_receipt_identity_mismatch"
    ):
        validate_promotion_receipt(proof, environment=wrong, product_sha="a" * 40)
