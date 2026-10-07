"""Record a passing fleet rehearsal where the project's release gate reads it.

A receipt belongs to the control plane the caller names, on the rehearsed
project environment's own settings document, whatever admin cluster the
copies were taken from. That plane must be a Yoke control plane holding the
project environment; any other connection is refused before rehearsal starts.
"""

from __future__ import annotations

import json
import os
import subprocess
from typing import List, Mapping, Sequence, Tuple

_RECEIPT_TIMEOUT_SECONDS = 120


def _run_on(receipt_env: str, argv: List[str]) -> str:
    """Run a registered command on *receipt_env*; return why it failed, if it did."""
    # The receipt belongs to the named control plane, not the separately
    # selected admin cluster, so the child gets its own env.
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
        return f"could not run: {exc}"
    if result.returncode != 0:
        return f"exited {result.returncode}: {(result.stderr or '').strip()}"
    return ""


def receipt_plane_refusal(*, receipt_env: str, project: str, environment: str) -> str:
    """Why *receipt_env* cannot hold this receipt, or ``""`` when it can.

    The probe is the registered settings read the release gate itself uses,
    so a connection that answers it is a Yoke control plane holding the
    project environment, and one that cannot — a Platform database login, a
    universe without the project — is refused by name.
    """
    from yoke_core.domain.environment_declared_facts import ADMIN_CONNECTION_PATH

    failure = _run_on(
        receipt_env,
        [
            "yoke",
            "projects",
            "environment-settings",
            "get",
            "--project",
            project,
            "--environment",
            environment,
            "--path",
            ADMIN_CONNECTION_PATH,
        ],
    )
    if not failure:
        return ""
    last_line = failure.strip().splitlines()[-1]
    return (
        f"--receipt-env {receipt_env} did not answer as a Yoke control plane "
        f"holding {project}/{environment}: the release gate's settings read failed "
        f"there ({last_line}). Name the control plane the release gate reads "
        "(`yoke env list`) and retry: yoke watch preflight -- --project "
        f"{project} {environment} --record-receipt --product-sha <sha> "
        "--receipt-env <control-plane>"
    )


def record_receipt(
    *,
    project: str,
    model: str,
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
            model,
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
    failure = _run_on(receipt_env, argv)
    if failure:
        return "", failure
    return run, ""


__all__ = ["receipt_plane_refusal", "record_receipt"]
