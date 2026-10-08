"""Successful promotion payload and corresponding immutable GitHub evidence."""

from yoke_core.domain.hosted_promotion_receipt import PROMOTION_ARTIFACT_PREFIX


def payload(**changes):
    return {
        "schema": 1,
        "repository": "upyoke/platform",
        "workflow": "yoke-release-promote.yml",
        "run_id": "123",
        "run_attempt": 1,
        "yoke_dispatch_id": "yd-" + "d" * 32,
        "target_environment": "stage",
        "product_sha": "a" * 40,
        "version": f"0.1.1+launch.{461}",
        "platform_sha": "b" * 40,
        "pin_pushed": True,
        "proven_consumer_sha": "c" * 40,
        **changes,
    }


def envelope(value=None):
    value = value or payload()
    return {
        "repository": value["repository"],
        "run_id": value["run_id"],
        "run_attempt": value["run_attempt"],
        "run_head_sha": "e" * 40,
        "workflow_path": f".github/workflows/{value['workflow']}",
        "display_title": f"promotion [yoke-dispatch:{value['yoke_dispatch_id']}]",
        "artifact_id": 456,
        "artifact_name": f"{PROMOTION_ARTIFACT_PREFIX}-{value['run_id']}-{value['run_attempt']}",
        "digest": "sha256:" + "f" * 64,
        "payload": value,
    }
