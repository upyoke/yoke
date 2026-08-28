"""``yoke aws`` source-dev/admin command adapters."""

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
from typing import Any, Dict, List, Optional

from yoke_cli.commands._helpers import ensure_handlers_loaded, parse_or_usage_error
from yoke_cli.commands.adapters.dev import DEFAULT_PROJECT_ID, PROJECT_ID_ENV
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher
from yoke_contracts.api.function_call import TargetRef

AWS_EXEC_USAGE = (
    "yoke aws exec [--project PROJECT] [--region REGION] -- <aws-args>"
)
AWS_ADMIN_LINK_USAGE = (
    "yoke aws admin-link [--project PROJECT] [--region REGION]"
)
_AWS_ADMIN_CAPABILITY = "aws-admin"


def aws_admin_link(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke aws admin-link",
        description=(
            "Print the one-click CloudFormation link that creates this "
            "project's aws-admin bootstrap credential. The stack makes an IAM "
            "user and an access key; both values appear as stack Outputs — "
            "paste them into `yoke onboard`. The link pins "
            "the template published with the running build."
        ),
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project slug or id the credential belongs to (informational).",
    )
    parser.add_argument(
        "--region",
        default=None,
        help="AWS region the console opens in (default: $AWS_REGION or us-east-1).",
    )
    parsed = parse_or_usage_error(parser, args, AWS_ADMIN_LINK_USAGE)
    if parsed is None:
        return 2

    from yoke_cli.config import aws_admin_capability

    url = aws_admin_capability.quick_create_url(region=parsed.region)
    if url is None:
        print(
            "error: this build or distribution channel has no supported "
            "CloudFormation bootstrap link. Reinstall from a hosted Yoke "
            "release, or choose existing AWS credentials in `yoke onboard`.",
            file=sys.stderr,
        )
        return 1
    print(url)
    return 0


def aws_exec(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke aws exec",
        description=(
            "Run the AWS CLI with the selected project's aws-admin "
            "capability credentials materialized only for the subprocess."
        ),
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project slug or id (default: $YOKE_PROJECT_ID or yoke).",
    )
    parser.add_argument(
        "--region",
        default=None,
        help="AWS region (default: aws-admin capability settings.region).",
    )
    parser.add_argument("aws_args", nargs=argparse.REMAINDER)
    parsed = parse_or_usage_error(parser, args, AWS_EXEC_USAGE)
    if parsed is None:
        return 2

    aws_args = list(parsed.aws_args)
    if aws_args and aws_args[0] == "--":
        aws_args = aws_args[1:]
    if not aws_args:
        print("error: missing AWS CLI arguments after --", file=sys.stderr)
        print(f"Usage: {AWS_EXEC_USAGE}", file=sys.stderr)
        return 2

    project = parsed.project or _default_project()
    try:
        region = parsed.region or _aws_admin_region(project)
        if not region:
            raise AwsExecAdapterError(
                f"project '{project}' aws-admin capability settings declare "
                "no region; set settings.region or pass --region"
            )
        # Machine-local secrets + relayed settings: works on https without a
        # local Postgres open (same shape as yoke pulumi exec / yoke vps).
        deploy_remote = importlib.import_module("yoke_core.domain.deploy_remote")
        env = deploy_remote.aws_machine_capability_env(project, region)
    except Exception as exc:
        print(f"error: aws-admin capability resolution failed: {exc}", file=sys.stderr)
        return 1

    try:
        completed = subprocess.run(["aws", *aws_args], env=env)
    except FileNotFoundError:
        print("error: aws CLI executable not found on PATH", file=sys.stderr)
        return 127
    return int(completed.returncode)


def _aws_admin_region(project: str, *, session_id: Optional[str] = None) -> Optional[str]:
    """Read aws-admin settings.region through the active control-plane transport."""
    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="projects.capability_settings.get",
        target=TargetRef(kind="global"),
        payload={"project": project, "cap_type": _AWS_ADMIN_CAPABILITY},
        actor=build_actor(session_id=session_id),
    )
    if not response.success:
        message = (
            response.error.message
            if response.error is not None
            else "capability settings read failed"
        )
        raise AwsExecAdapterError(message)
    result: Dict[str, Any] = response.result or {}
    settings_json = result.get("settings_json")
    if settings_json is None:
        return None
    parsed = json.loads(str(settings_json))
    if not isinstance(parsed, dict):
        raise AwsExecAdapterError(
            f"project '{project}' aws-admin capability settings must be a JSON object"
        )
    region = str(parsed.get("region") or "").strip()
    return region or None


def _default_project() -> str:
    import os

    return os.environ.get(PROJECT_ID_ENV) or DEFAULT_PROJECT_ID


class AwsExecAdapterError(RuntimeError):
    """The requested AWS command lacks capability-owned configuration."""
