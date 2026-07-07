"""``yoke aws`` source-dev/admin command adapters."""

from __future__ import annotations

import argparse
import importlib
import subprocess
import sys
from typing import List

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.commands.adapters.dev import DEFAULT_PROJECT_ID, PROJECT_ID_ENV

AWS_EXEC_USAGE = (
    "yoke aws exec [--project PROJECT] [--region REGION] -- <aws-args>"
)


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
        deploy_remote = importlib.import_module("yoke_core.domain.deploy_remote")
        region = parsed.region or deploy_remote.aws_capability_region(project)
        if not region:
            raise AwsExecAdapterError(
                f"project '{project}' aws-admin capability settings declare "
                "no region; set settings.region or pass --region"
            )
        env = deploy_remote.aws_capability_env(project, region)
    except Exception as exc:
        print(f"error: aws-admin capability resolution failed: {exc}", file=sys.stderr)
        return 1

    try:
        completed = subprocess.run(["aws", *aws_args], env=env)
    except FileNotFoundError:
        print("error: aws CLI executable not found on PATH", file=sys.stderr)
        return 127
    return int(completed.returncode)


def _default_project() -> str:
    import os

    return os.environ.get(PROJECT_ID_ENV) or DEFAULT_PROJECT_ID


class AwsExecAdapterError(RuntimeError):
    """The requested AWS command lacks capability-owned configuration."""
