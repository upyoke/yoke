"""Validate the hosted promotion's exact identity and artifact provenance."""

from __future__ import annotations

import re
from typing import Any

PROMOTION_ARTIFACT_PREFIX = "promotion-receipt"
PROMOTION_RECEIPTS_KEY = "promotion_receipts"
HOSTED_BRIDGE_WORKFLOW = "platform-release-bridge.yml"


class PromotionReceiptRefused(ValueError):
    def __init__(self, reason: str, detail: str):
        super().__init__(
            f"{reason}: {detail}; read the exact successful promotion "
            "receipt and record it again; do not redeploy a shipped release"
        )
        self.reason = reason


def full_sha(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(r"[0-9a-f]{40}", value))


def validate_promotion_receipt(
    envelope: Any,
    *,
    environment: str,
    product_sha: str,
    commit_sha: str = "",
) -> dict:
    if not isinstance(envelope, dict) or not isinstance(envelope.get("payload"), dict):
        raise PromotionReceiptRefused(
            "promotion_receipt_missing", "no attributable promotion receipt"
        )
    payload = envelope["payload"]
    required = {
        "schema",
        "repository",
        "workflow",
        "run_id",
        "run_attempt",
        "yoke_dispatch_id",
        "target_environment",
        "product_sha",
        "version",
        "platform_sha",
        "pin_pushed",
        "proven_consumer_sha",
    }
    if (
        set(payload) != required
        or type(payload.get("schema")) is not int
        or payload["schema"] != 1
    ):
        raise PromotionReceiptRefused(
            "promotion_receipt_schema_invalid", "expected the agreed promotion schema"
        )
    for key in ("product_sha", "platform_sha"):
        if not full_sha(payload.get(key)):
            raise PromotionReceiptRefused(
                "promotion_receipt_sha_invalid",
                f"{key} must be a full lowercase commit SHA",
            )
    if not full_sha(payload.get("proven_consumer_sha")):
        raise PromotionReceiptRefused(
            "promotion_receipt_consumer_unproven",
            "bound hosted promotion names no exact proven consumer",
        )
    run_id = payload.get("run_id")
    attempt = payload.get("run_attempt")
    if (
        not isinstance(run_id, str)
        or not run_id.isdecimal()
        or int(run_id) < 1
        or type(attempt) is not int
        or attempt < 1
        or type(payload.get("pin_pushed")) is not bool
    ):
        raise PromotionReceiptRefused(
            "promotion_receipt_run_invalid",
            "receipt names no exact run attempt or pin outcome",
        )
    version = payload.get("version")
    if (
        not isinstance(version, str)
        or not version
        or len(version.split()) != 1
        or version.startswith("v")
    ):
        raise PromotionReceiptRefused(
            "promotion_receipt_version_invalid", "receipt names no release version"
        )
    correlation = payload.get("yoke_dispatch_id")
    if not isinstance(correlation, str) or not re.fullmatch(
        r"yd-[0-9a-f]{32}", correlation
    ):
        raise PromotionReceiptRefused(
            "promotion_receipt_correlation_invalid",
            "receipt names no dispatch correlation",
        )
    expected = {
        "repository": "upyoke/platform",
        "workflow": "yoke-release-promote.yml",
        "target_environment": environment,
        "product_sha": product_sha,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise PromotionReceiptRefused(
                "promotion_receipt_identity_mismatch",
                f"{key} does not match this deployment",
            )
    if commit_sha and (
        not full_sha(commit_sha) or payload["platform_sha"] != commit_sha
    ):
        raise PromotionReceiptRefused(
            "promotion_receipt_commit_mismatch",
            "--commit differs from the deployed promotion SHA",
        )
    if (
        envelope.get("repository") != payload["repository"]
        or envelope.get("run_id") != run_id
        or envelope.get("run_attempt") != attempt
        or envelope.get("workflow_path") != f".github/workflows/{payload['workflow']}"
        or envelope.get("artifact_name")
        != f"{PROMOTION_ARTIFACT_PREFIX}-{run_id}-{attempt}"
        or f"[yoke-dispatch:{correlation}]"
        not in str(envelope.get("display_title") or "")
        or not full_sha(envelope.get("run_head_sha"))
        or type(envelope.get("artifact_id")) is not int
        or envelope["artifact_id"] < 1
        or not re.fullmatch(r"sha256:[0-9a-f]{64}", str(envelope.get("digest") or ""))
    ):
        raise PromotionReceiptRefused(
            "promotion_receipt_provenance_mismatch",
            "receipt disagrees with its GitHub artifact/run provenance",
        )
    return dict(payload)


def project_promotion_receipts(sources: dict, project_id: int) -> list[dict]:
    for entry in sources.get("projects") or []:
        if entry.get("project_id") == project_id:
            return list(entry.get(PROMOTION_RECEIPTS_KEY) or [])
    return []


def requires_promotion_identity(run: dict, sources: dict, project_id: int) -> bool:
    import json

    project = next(
        (
            entry.get("project")
            for entry in sources.get("projects") or []
            if entry.get("project_id") == project_id
        ),
        None,
    )
    if not project:
        return False
    stages = run.get("stages") or []
    if isinstance(stages, str):
        stages = json.loads(stages)
    return any(
        stage.get("workflow") == HOSTED_BRIDGE_WORKFLOW
        and any(
            binding.get("project") == project
            for binding in (stage.get("input_bindings") or {}).values()
        )
        for stage in stages
    )
