# AUTO-GENERATED template source: templates/webapp/infra/webapp_runner_authority_intent.py. Do not hand-edit rendered copies; refresh through Yoke template/onboarding surfaces.
"""Fail-closed binding between validated Yoke authority and Pulumi config."""

from __future__ import annotations

import hashlib
import hmac
import json
import os

import pulumi


AUTHORITY_INTENT_ENV = "YOKE_RUNNER_FLEET_AUTHORITY_INTENT"


def require_matching_authority_intent(
    args: object,
    *,
    stack_name: str,
) -> None:
    """Refuse mutable Pulumi config that differs from validated authority."""
    raw = os.environ.get(AUTHORITY_INTENT_ENV, "")
    try:
        envelope = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise pulumi.RunError(
            "runner-fleet requires a valid Yoke authority-intent envelope"
        ) from exc
    if not isinstance(envelope, dict) or envelope.get("schema") != 1:
        raise pulumi.RunError(
            "runner-fleet requires authority-intent envelope schema 1"
        )
    expected = envelope.get("authority")
    digest = str(envelope.get("sha256") or "")
    if not isinstance(expected, dict):
        raise pulumi.RunError(
            "runner-fleet authority-intent envelope omitted its authority"
        )
    canonical = json.dumps(expected, sort_keys=True, separators=(",", ":"))
    actual_digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    if not hmac.compare_digest(digest, actual_digest):
        raise pulumi.RunError(
            "runner-fleet authority-intent envelope digest is invalid"
        )
    actual = _authority_from_args(args, stack_name=stack_name)
    if actual != expected:
        mismatched = sorted(
            key
            for key in set(actual) | set(expected)
            if actual.get(key) != expected.get(key)
        )
        raise pulumi.RunError(
            "runner-fleet Pulumi config does not match validated authority "
            "intent; mismatched fields: " + ", ".join(mismatched)
        )


def _authority_from_args(
    args: object,
    *,
    stack_name: str,
) -> dict[str, object]:
    return {
        "project": str(getattr(args, "project")),
        "deploy_namespace": str(getattr(args, "deploy_namespace")),
        "stack_name": str(stack_name),
        "aws_capability": str(getattr(args, "aws_capability")),
        "aws_region": str(getattr(args, "aws_region")),
        "github_capability": str(getattr(args, "github_capability")),
        "repo": str(getattr(args, "github_repo")),
        "repo_owner": str(getattr(args, "github_repo_owner")),
        "repo_name": str(getattr(args, "github_repo_name")),
        "installation_id": str(getattr(args, "github_installation_id")),
        "repository_id": str(getattr(args, "github_repository_id")),
        "app_issuer": str(getattr(args, "github_app_issuer")),
        "api_url": str(getattr(args, "github_api_url")),
        "web_url": str(getattr(args, "github_web_url")),
        "private_key_secret_arn": str(getattr(args, "github_private_key_secret_arn")),
        "runner_labels": [str(label) for label in getattr(args, "runner_labels")],
        "runner_variable_name": str(getattr(args, "runner_variable_name")),
        "routing_enabled": bool(getattr(args, "routing_enabled")),
        "runner_count": int(getattr(args, "runner_count")),
        "max_runner_count": int(getattr(args, "max_runner_count")),
        "instance_type": str(getattr(args, "instance_type")),
        "architecture": str(getattr(args, "architecture")),
        "root_volume_gb": int(getattr(args, "root_volume_gb")),
        "idle_shutdown_minutes": int(getattr(args, "idle_shutdown_minutes")),
        "shutdown_mode": str(getattr(args, "shutdown_mode")),
        "deployment_ssh_stack_outputs": {
            str(stack_name): str(output_name)
            for stack_name, output_name in getattr(
                args, "deployment_ssh_stack_outputs"
            ).items()
        },
    }


__all__ = ["AUTHORITY_INTENT_ENV", "require_matching_authority_intent"]
