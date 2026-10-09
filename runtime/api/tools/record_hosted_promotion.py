"""Record a completed hosted promotion using its immutable attempt receipt.

This is bookkeeping after delivery. Failure names a receipt recovery, never
a request to repeat the successful deployment. The bridge annotates failure;
hosted bound-project QA requires recorded delivered identity before credit.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from runtime.api.tools.require_platform_consumer_compatibility import (
    CONSUMER_PROJECT,
    CONSUMER_REPO,
    _yoke,
    bind_consumer_authority,
)
from yoke_core.domain.hosted_promotion_receipt import (
    PROMOTION_ARTIFACT_PREFIX,
    PromotionReceiptRefused,
    full_sha,
    validate_promotion_receipt,
)

READER_READINESS_SECONDS = 600
READINESS_POLL_SECONDS = 15


def read_receipt(promotion_run_id: str) -> dict:
    unavailable = bind_consumer_authority()
    if unavailable:
        raise PromotionReceiptRefused(
            "promotion_receipt_authority_unavailable", unavailable
        )
    deadline = time.monotonic() + READER_READINESS_SECONDS
    while True:
        code, stdout, stderr = _yoke(
            [
                "github-actions",
                "wait-run",
                CONSUMER_REPO,
                promotion_run_id,
                "--project",
                CONSUMER_PROJECT,
                "--timeout",
                "0",
                "--receipt-artifact-prefix",
                PROMOTION_ARTIFACT_PREFIX,
                "--json",
            ],
            timeout=300,
        )
        try:
            response = json.loads(stdout)
            result = response.get("result") or {}
            if not isinstance(result, dict):
                raise ValueError("receipt result must be an object")
        except (ValueError, AttributeError):
            raise PromotionReceiptRefused(
                "promotion_receipt_response_invalid",
                "receipt read returned no structured response",
            ) from None
        if (
            code == 0
            and response.get("success")
            and isinstance(result.get("receipt"), dict)
        ):
            receipt = result["receipt"]
            if receipt.get("run_id") != promotion_run_id:
                raise PromotionReceiptRefused(
                    "promotion_receipt_run_mismatch",
                    "reader returned another promotion run",
                )
            return receipt
        detail = str(
            result.get("message")
            or (response.get("error") or {}).get("message")
            or stderr
            or "no receipt"
        )
        # A production self-release installs this reader before bookkeeping.
        # Its parallel Stage sibling can finish first; bounded readiness lets
        # that same completed promotion wait for the API build, without
        # redispatching either promotion or following a mutable source ref.
        retryable = (
            "workflow_receipt_reader_unavailable" in detail
            or result.get("state") == "timeout"
            or not response.get("success")
        )
        if retryable and time.monotonic() < deadline:
            print(
                "Promotion receipt reader not ready; retaining the exact completed run",
                file=sys.stderr,
                flush=True,
            )
            time.sleep(READINESS_POLL_SECONDS)
            continue
        raise PromotionReceiptRefused("promotion_receipt_unavailable", detail)


def record(args) -> tuple[int, str]:
    if not full_sha(args.product_sha) or not full_sha(args.consumer_sha):
        raise PromotionReceiptRefused(
            "promotion_candidate_invalid",
            "product and bound consumer must be full commit SHAs",
        )
    receipt = read_receipt(args.promotion_run_id)
    payload = validate_promotion_receipt(
        receipt,
        environment=args.environment,
        product_sha=args.product_sha,
    )
    if payload["version"] != args.version:
        raise PromotionReceiptRefused(
            "promotion_receipt_version_mismatch",
            "receipt release differs from this bridge's annotated release",
        )
    # Source ancestry, final reproof identity and the run's own bound candidate
    # are checked by the guarded server writer before it changes any record.
    directory = Path(os.environ["RUNNER_TEMP"])
    path = (
        directory
        / f"promotion-receipt-{args.promotion_run_id}-{receipt['run_attempt']}.json"
    )
    content = json.dumps(receipt, sort_keys=True) + "\n"
    try:
        with path.open("x") as handle:
            handle.write(content)
    except FileExistsError:
        if path.read_text() != content:
            raise PromotionReceiptRefused(
                "promotion_receipt_file_changed", "local immutable receipt differs"
            )
    command = [
        "yoke",
        "deployment-runs",
        "release-output",
        "record",
        args.deployment_run_id,
        "--project",
        args.project,
        "--commit",
        payload["platform_sha"],
        "--promotion-receipt-file",
        str(path),
        "--json",
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=300)
    if completed.returncode:
        recovery = " ".join(command[:-1])
        return completed.returncode, (
            "promotion_receipt_unrecorded: this promotion shipped; inspect "
            f"the named refusal and recover its receipt with {recovery}\n"
            f"{completed.stderr or completed.stdout}"
        )
    return 0, completed.stdout


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deployment-run-id", required=True)
    parser.add_argument("--promotion-run-id", required=True)
    parser.add_argument("--environment", required=True, choices=("stage", "prod"))
    parser.add_argument("--product-sha", required=True)
    parser.add_argument("--consumer-sha", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--project", required=True)
    args = parser.parse_args(argv)
    try:
        code, detail = record(args)
    except (
        PromotionReceiptRefused,
        OSError,
        subprocess.SubprocessError,
        KeyError,
    ) as exc:
        print(
            f"promotion_receipt_unrecorded: {exc}; preserve promotion run "
            f"{args.promotion_run_id} and re-run this receipt tool with the same "
            "arguments after repairing the reader; do not redeploy",
            file=sys.stderr,
        )
        return 1
    print(detail, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
