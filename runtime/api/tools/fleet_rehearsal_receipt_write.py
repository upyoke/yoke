"""Record a passing fleet rehearsal where the project's release gate reads it.

A receipt belongs to the prod release-gate control plane, on the rehearsed
project environment's own settings document, whatever admin cluster the
copies were taken from.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import Mapping, Sequence, Tuple

from yoke_contracts.machine_config import runtime as machine_config
from yoke_contracts.machine_config.schema import (
    connection_is_prod,
    same_universe_https_env,
)

_RECEIPT_TIMEOUT_SECONDS = 120


def release_gate_receipt_env() -> str:
    """Return the configured product connection owning release evidence."""
    config = machine_config.load_config()
    connections = config.get("connections")
    if not isinstance(connections, Mapping):
        return ""
    authorities = {
        same_universe_https_env(config, str(env)) or str(env)
        for env, connection in connections.items()
        if isinstance(connection, Mapping) and connection_is_prod(connection)
    }
    return next(iter(authorities)) if len(authorities) == 1 else ""


def record_receipt(
    *,
    project: str,
    receipt_env: str,
    environment: str,
    product_sha: str,
    entries: Sequence[str],
    engine_artifact: Mapping[str, str],
    schema_shape_digest: str,
    database_count: int,
) -> Tuple[str, str]:
    """Write the pass to the control plane; return the run id and any reason."""
    from yoke_core.domain import migration_preflight_receipt as receipt

    covered_env = receipt.target_environment_for_admin_env(environment)
    try:
        run, assignments = receipt.receipt_assignments(
            product_sha,
            entries,
            engine_artifact=engine_artifact,
            schema_shape_digest=schema_shape_digest,
            database_count=database_count,
        )
    except receipt.ReceiptPathError as exc:
        return "", str(exc)
    argv = [
        "yoke",
        "projects",
        "environment-settings",
        "merge",
        "--project",
        project,
        "--environment",
        covered_env,
    ]
    for path, value in assignments.items():
        argv += ["--set", f"{path}={json.dumps(value)}"]
    # The receipt belongs to the control plane the release gate will read, not
    # the separately selected admin cluster, so the child gets its own env.
    child_env = dict(os.environ, YOKE_ENV=receipt_env)
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=_RECEIPT_TIMEOUT_SECONDS,
            env=child_env,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", f"could not run: {exc}"
    if result.returncode != 0:
        return "", f"exited {result.returncode}: {(result.stderr or '').strip()}"
    return run, ""


__all__ = ["record_receipt", "release_gate_receipt_env"]
