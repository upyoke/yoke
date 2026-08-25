"""Independent local validation for a consumed stage qualification grant."""

from __future__ import annotations

import subprocess
from pathlib import Path

from yoke_cli.config import machine_config
from yoke_contracts.machine_config.schema import connection_is_prod
from yoke_harness.session_relay_runtime import RelayExecutionContext


_SOURCE_PATH = Path(
    "packages/yoke-harness/src/yoke_harness/session_relay_private_qualification.py"
)


def _clean_source_sha() -> str | None:
    source_file = Path(__file__).resolve()
    try:
        root = subprocess.run(
            ["git", "-C", str(source_file.parent), "rev-parse", "--show-toplevel"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        if root.returncode:
            return None
        source_checkout = Path(root.stdout.strip()).resolve()
        if source_file != source_checkout / _SOURCE_PATH:
            return None
        head = subprocess.run(
            ["git", "-C", str(source_checkout), "rev-parse", "HEAD"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
        status = subprocess.run(
            ["git", "-C", str(source_checkout), "status", "--porcelain"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if head.returncode or status.returncode or status.stdout.strip():
        return None
    value = head.stdout.strip()
    return value if len(value) == 40 else None


def private_route_qualification_allows(
    context: RelayExecutionContext,
    *,
    operation: str,
) -> bool:
    grant = context.private_route_qualification
    if grant is None or grant.expired():
        return False
    scope = grant.scope
    try:
        environment = machine_config.active_env()
        connection = machine_config.active_connection()
    except Exception:
        return False
    if environment != "stage" or connection_is_prod(connection):
        return False
    if (
        grant.project_id != context.project_id
        or not grant.sender_session_id
        or not grant.operator_actor_id.isdigit()
        or grant.grant_digest != scope.digest
        or scope.environment != "stage"
        or scope.surface != context.surface
        # The grant attests this exact stage-tested binary. A floor would let an
        # untested build consume proof minted for a different executable.
        or scope.version != context.surface_version
        or scope.operation != operation
        or scope.route != context.wake_route
    ):
        return False
    return _clean_source_sha() == scope.release_sha


__all__ = ["private_route_qualification_allows"]
