"""HTTPS-safe ``yoke release-pin verify`` adapter."""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List, Optional

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.deployment_pin import RELEASE_PIN_CAPABILITY
from yoke_cli.commands.release_pin_agreement import (
    DESIRED_PIN_SETTINGS_PATH,
    HEALTH_PROBE_SETTINGS_PATH,
    environment_id_for_target,
    evaluate_pin_health_agreement,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.api.function_call import TargetRef

VERIFY_USAGE = (
    "yoke release-pin verify --project NAME --environment ENV "
    "[--session-id S] [--json]"
)


def release_pin_verify(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke release-pin verify")
    parser.add_argument("--project", required=True)
    parser.add_argument(
        "--environment",
        required=True,
        help="Deploy target name (stage or production).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, VERIFY_USAGE)
    if parsed is None:
        return 2

    settings = _capability_settings(parsed.project, parsed.session_id)
    if settings is None:
        return usage_error(
            f"project {parsed.project!r} has no {RELEASE_PIN_CAPABILITY} capability"
        )
    environment_id = environment_id_for_target(settings, parsed.environment)
    if not environment_id:
        return usage_error(
            f"release_pin.environment_by_target has no entry for "
            f"{parsed.environment!r}"
        )
    values = _environment_values(
        parsed.project,
        environment_id,
        [DESIRED_PIN_SETTINGS_PATH, HEALTH_PROBE_SETTINGS_PATH],
        parsed.session_id,
    )
    agreement = evaluate_pin_health_agreement(
        desired_pin=_scalar(values.get(DESIRED_PIN_SETTINGS_PATH)),
        probe_url=_scalar(values.get(HEALTH_PROBE_SETTINGS_PATH)),
    )
    payload = {
        "project": parsed.project,
        "environment": parsed.environment,
        "environment_id": environment_id,
        "agreed": agreement.agreed,
        "desired_pin": agreement.desired_pin,
        "served_engine_version": agreement.served_engine_version,
        "probe_url": agreement.probe_url,
        "skipped_reason": agreement.skipped_reason,
        "error": agreement.error,
    }
    if parsed.json_mode:
        print(json.dumps({"success": agreement.agreed, "result": payload}, sort_keys=True))
    else:
        _print_human(payload)
    if agreement.error:
        return 1
    if agreement.skipped_reason:
        return 0
    return 0 if agreement.agreed else 1


def _print_human(payload: Dict[str, Any]) -> None:
    if payload.get("skipped_reason"):
        print(f"release-pin: skipped — {payload['skipped_reason']}")
        return
    if payload.get("error"):
        print(f"release-pin: probe failed — {payload['error']}")
        return
    desired = payload.get("desired_pin")
    served = payload.get("served_engine_version")
    if payload.get("agreed"):
        print(f"release-pin: {desired} agrees with health probe")
        return
    print(
        f"release-pin: desired {desired} disagrees with served {served} "
        f"at {payload.get('probe_url')}"
    )


def _scalar(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _capability_settings(
    project: str, session_id: Optional[str]
) -> Optional[dict]:
    result = _read(
        "projects.capability_settings.get",
        {"project": project, "cap_type": RELEASE_PIN_CAPABILITY},
        session_id,
    )
    if result is None:
        return None
    settings = json.loads(str(result.get("settings_json") or "null"))
    return settings if isinstance(settings, dict) else None


def _environment_values(
    project: str,
    environment_id: str,
    paths: List[str],
    session_id: Optional[str],
) -> Dict[str, Any]:
    result = _read(
        "projects.environment_settings.get",
        {
            "project": project,
            "environment_id": environment_id,
            "paths": paths,
        },
        session_id,
    )
    values = (result or {}).get("values") or {}
    return values if isinstance(values, dict) else {}


def _read(
    function_id: str, payload: Dict[str, Any], session_id: Optional[str]
) -> Optional[Dict[str, Any]]:
    response = call_dispatcher(
        function_id=function_id,
        target=TargetRef(kind="global"),
        payload=payload,
        actor=build_actor(session_id=session_id),
    )
    return response.result if response.success else None


__all__ = ["VERIFY_USAGE", "release_pin_verify"]
