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
from yoke_contracts.release_pin import (
    DESIRED_PIN_PATH_KEY,
    PROBE_URL_PATH_KEY,
    SERVED_PIN_RESPONSE_PATH_KEY,
)
from yoke_cli.commands.deployment_pin import RELEASE_PIN_CAPABILITY
from yoke_cli.commands.release_pin_agreement import (
    evaluate_pin_health_agreement,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.api.function_call import TargetRef

VERIFY_USAGE = (
    "yoke release-pin verify --project NAME --environment ENV [--session-id S] [--json]"
)


def release_pin_verify(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke release-pin verify")
    parser.add_argument("--project", required=True)
    parser.add_argument(
        "--environment",
        required=True,
        help=(
            "Registered environment name for the project."
        ),
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
    environment = str(parsed.environment or "").strip()
    registered = _project_environment_names(parsed.project, parsed.session_id)
    if environment not in registered:
        return usage_error(
            f"environment {environment!r} is not registered for project "
            f"{parsed.project!r}; registered: "
            f"{', '.join(registered) or '(none)'}"
        )
    desired_pin_path = _scalar(settings.get(DESIRED_PIN_PATH_KEY))
    if not desired_pin_path:
        return usage_error(
            f"release_pin.{DESIRED_PIN_PATH_KEY} must explicitly name the "
            "desired pin leaf"
        )
    probe_url_path = _scalar(settings.get(PROBE_URL_PATH_KEY))
    if not probe_url_path:
        return usage_error(
            f"release_pin.{PROBE_URL_PATH_KEY} must explicitly name the probe URL leaf"
        )
    served_pin_response_path = _scalar(settings.get(SERVED_PIN_RESPONSE_PATH_KEY))
    if not served_pin_response_path:
        return usage_error(
            f"release_pin.{SERVED_PIN_RESPONSE_PATH_KEY} must explicitly "
            "name the served-pin JSON response leaf"
        )
    values = _environment_values(
        parsed.project,
        environment,
        [desired_pin_path, probe_url_path],
        parsed.session_id,
    )
    agreement = evaluate_pin_health_agreement(
        desired_pin=_scalar(values.get(desired_pin_path)),
        probe_url=_scalar(values.get(probe_url_path)),
        desired_path=desired_pin_path,
        probe_url_path=probe_url_path,
        served_pin_response_path=served_pin_response_path,
    )
    payload = {
        "project": parsed.project,
        "environment": parsed.environment,
        "settings_path": desired_pin_path,
        "probe_url_path": probe_url_path,
        "served_pin_response_path": served_pin_response_path,
        "agreed": agreement.agreed,
        "desired_pin": agreement.desired_pin,
        "served_pin": agreement.served_pin,
        "probe_url": agreement.probe_url,
        "error": agreement.error,
    }
    if parsed.json_mode:
        print(
            json.dumps({"success": agreement.agreed, "result": payload}, sort_keys=True)
        )
    else:
        _print_human(payload)
    if agreement.error:
        return 1
    return 0 if agreement.agreed else 1


def _print_human(payload: Dict[str, Any]) -> None:
    if payload.get("error"):
        print(f"release-pin: probe failed — {payload['error']}")
        return
    desired = payload.get("desired_pin")
    served = payload.get("served_pin")
    if payload.get("agreed"):
        print(f"release-pin: {desired} agrees with health probe")
        return
    print(
        f"release-pin: desired {desired} disagrees with served {served} "
        f"at {payload.get('probe_url')}"
    )


def _scalar(value: Any) -> Optional[str]:
    if value is None or isinstance(value, (dict, list)):
        return None
    text = str(value).strip()
    return text or None


def _capability_settings(project: str, session_id: Optional[str]) -> Optional[dict]:
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
    environment: str,
    paths: List[str],
    session_id: Optional[str],
) -> Dict[str, Any]:
    result = _read(
        "projects.environment_settings.get",
        {
            "project": project,
            "environment": environment,
            "paths": paths,
        },
        session_id,
    )
    values = (result or {}).get("values") or {}
    return values if isinstance(values, dict) else {}


def _project_environment_names(
    project: str, session_id: Optional[str]
) -> List[str]:
    result = _read(
        "projects.infrastructure.list",
        {"project": project},
        session_id,
    )
    rows = (result or {}).get("environments") or []
    return sorted({
        str(row.get("name") or "").strip()
        for row in rows
        if isinstance(row, dict) and str(row.get("name") or "").strip()
    })


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
