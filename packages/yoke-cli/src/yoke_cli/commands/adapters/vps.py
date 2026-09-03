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
import sys
from typing import Any, List, Mapping

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.commands.adapters.dev import PROJECT_ID_ENV

VPS_POWER_USAGE = (
    "yoke vps <status|stop|start> --stack STACK [--project P] [--region R]"
)

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


def _aws_sdk() -> Any:
    # The CLI wheel keeps its engine edge dynamic; product-boundary inventory
    # classifies this one machine-local credential operation explicitly.
    try:
        return importlib.import_module("yoke_core.domain.aws_machine_client")
    except Exception as exc:  # noqa: BLE001 - translated to operator recovery
        raise VpsPowerError(
            f"AWS SDK support is unavailable ({type(exc).__name__}); "
            "reinstall Yoke and retry"
        ) from exc


def _ec2_client(project: str, region: str, sdk: Any) -> Any:
    try:
        return sdk.machine_aws_client("ec2", project, region)
    except Exception as exc:  # noqa: BLE001 - raw SDK state may contain secrets
        reason = sdk.safe_aws_error_reason(exc)
        raise VpsPowerError(
            f"could not prepare project '{project}' AWS authority ({reason}); "
            f"verify it with `yoke aws admin-status --project {project}` and retry"
        ) from exc


def _resolve(stack: str, client: Any) -> tuple[str, str]:
    """Return ``(instance_id, state)`` for the stack's VPS host."""
    response = client.describe_instances(
        Filters=[
            {
                "Name": "tag:Name",
                "Values": [f"{stack}{_INSTANCE_SUFFIX}"],
            }
        ],
    )
    found: list[tuple[str, str]] = []
    if isinstance(response, Mapping):
        for reservation in response.get("Reservations") or []:
            if not isinstance(reservation, Mapping):
                continue
            for instance in reservation.get("Instances") or []:
                if not isinstance(instance, Mapping):
                    continue
                instance_id = str(instance.get("InstanceId") or "").strip()
                state_row = instance.get("State")
                state = (
                    str(state_row.get("Name") or "").strip()
                    if isinstance(state_row, Mapping)
                    else ""
                )
                if instance_id and state and state != "terminated":
                    found.append((instance_id, state))
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
        sdk = _aws_sdk()
        client = _ec2_client(project, parsed.region, sdk)
        instance_id, state = _resolve(parsed.stack, client)
        if verb == "status":
            print(f"{parsed.stack}: {instance_id} is {state}")
            return 0
        wanted = "running" if verb == "start" else "stopped"
        if state == wanted:
            print(f"{parsed.stack}: {instance_id} is already {state}")
            return 0
        operation = getattr(client, f"{verb}_instances")
        operation(InstanceIds=[instance_id])
    except VpsPowerError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - raw SDK state may contain secrets
        reason = sdk.safe_aws_error_reason(exc)
        print(
            f"error: vps {verb} failed ({reason}); verify project '{project}' "
            f"with `yoke aws admin-status --project {project}` and retry",
            file=sys.stderr,
        )
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
