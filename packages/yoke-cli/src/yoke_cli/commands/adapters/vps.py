"""``yoke vps`` source-dev/admin power controls for a Pulumi-managed VPS host.

A non-production host bills around the clock whether or not anyone is using
it. These commands stop and start one on demand so it can be parked between
development sessions, without putting a schedule into the infrastructure that
would also have to know when CI needs the host awake.

Stopping keeps the instance and its data: the root volume and the Elastic IP
survive and keep billing, so the saving is the instance-hours only. The host
returns on ``start`` with the same address.
"""

from __future__ import annotations

import argparse
import importlib
import json
import subprocess
import sys
from typing import List

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.commands.adapters.dev import PROJECT_ID_ENV

VPS_POWER_USAGE = "yoke vps <status|stop|start> --stack STACK [--project P] [--region R]"

#: Pulumi tags the instance ``<stack name>/VpsInstance``.
_INSTANCE_SUFFIX = "/VpsInstance"


class VpsPowerError(RuntimeError):
    """The requested host could not be resolved or controlled."""


def _parser(verb: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=f"yoke vps {verb}",
        description=__doc__.splitlines()[0],
    )
    parser.add_argument(
        "--stack",
        required=True,
        help="Pulumi stack that owns the host, e.g. yoke-platform-stage-vps.",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project slug owning the aws-admin capability (default: platform).",
    )
    parser.add_argument("--region", default="us-east-1", help="AWS region.")
    return parser


def _aws(args: List[str], env: dict) -> str:
    result = subprocess.run(
        ["aws", *args], env=env, capture_output=True, text=True,
    )
    if result.returncode:
        raise VpsPowerError((result.stderr or result.stdout).strip())
    return result.stdout.strip()


def _capability_env(project: str, region: str) -> dict:
    # Resolved through importlib, as the sibling aws adapter does: this package
    # must not take a static import on the engine, and the boundary test walks
    # the AST for exactly that.
    #
    # The machine-local resolver is used rather than the DB-backed one so this
    # works from an ordinary https-connected session; the credentials still
    # come from the project's aws-admin capability store, never the shell.
    deploy_remote = importlib.import_module("yoke_core.domain.deploy_remote")
    return deploy_remote.aws_machine_capability_env(project, region)


def _resolve(stack: str, env: dict) -> tuple[str, str]:
    """Return ``(instance_id, state)`` for the stack's VPS host."""
    raw = _aws(
        [
            "ec2", "describe-instances",
            "--filters", f"Name=tag:Name,Values={stack}{_INSTANCE_SUFFIX}",
            "--query", "Reservations[].Instances[].[InstanceId,State.Name]",
            "--output", "json",
        ],
        env,
    )
    found = [row for row in json.loads(raw or "[]") if row[1] != "terminated"]
    if not found:
        raise VpsPowerError(
            f"no live instance tagged {stack}{_INSTANCE_SUFFIX}; "
            "check the stack name with `yoke vps status --stack ...`"
        )
    if len(found) > 1:
        raise VpsPowerError(f"{stack} resolves to {len(found)} live instances")
    return found[0][0], found[0][1]


def _run(verb: str, args: List[str]) -> int:
    parsed = parse_or_usage_error(_parser(verb), args, VPS_POWER_USAGE)
    if parsed is None:
        return 2
    project = parsed.project or _default_project()
    try:
        env = _capability_env(project, parsed.region)
        instance_id, state = _resolve(parsed.stack, env)
        if verb == "status":
            print(f"{parsed.stack}: {instance_id} is {state}")
            return 0
        wanted = "running" if verb == "start" else "stopped"
        if state == wanted:
            print(f"{parsed.stack}: {instance_id} is already {state}")
            return 0
        _aws(
            [
                "ec2", f"{verb}-instances",
                "--instance-ids", instance_id,
                "--output", "json",
            ],
            env,
        )
    except VpsPowerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # capability resolution and AWS CLI absence
        print(f"error: vps {verb} failed: {exc}", file=sys.stderr)
        return 1
    settling = "starting" if verb == "start" else "stopping"
    print(f"{parsed.stack}: {instance_id} {settling} (was {state})")
    return 0


def vps_status(args: List[str]) -> int:
    return _run("status", args)


def vps_stop(args: List[str]) -> int:
    return _run("stop", args)


def vps_start(args: List[str]) -> int:
    return _run("start", args)


def _default_project() -> str:
    import os

    return os.environ.get(PROJECT_ID_ENV) or _DEFAULT_VPS_PROJECT


#: VPS hosts in this installation belong to the platform project, not the
#: default project a bare ``yoke`` command assumes.
_DEFAULT_VPS_PROJECT = "platform"

__all__ = ["vps_start", "vps_status", "vps_stop"]
