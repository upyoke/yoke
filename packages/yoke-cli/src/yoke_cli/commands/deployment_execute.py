"""Client-local deployment-run executor.

The run record belongs to an owner-only Postgres connection while GitHub App
operations relay through that connection's HTTPS sibling. Keeping this as a
tool-shaped command gives operators one stable installed entrypoint instead
of requiring a source checkout, an editable import, and two coordinated
environment variables.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Callable, Dict, List, Tuple

from yoke_contracts.machine_config.schema import (
    DB_ADMIN_ENV_SUFFIX,
    ENV_OVERRIDE,
)


AdapterFn = Callable[[List[str]], int]
DEPLOYMENT_RUNS_EXECUTE_USAGE = (
    "yoke --env CONTROL-PLANE-ENV-db-admin deployment-runs execute RUN-ID "
    "[--timeout MIN] [--from-stage STAGE] [--fresh] "
    "[--product-repo-path PATH] [--image-tag TAG]"
)


def deployment_runs_execute(args: List[str]) -> int:
    """Execute or resume a run through the selected admin connection."""
    if args in (["-h"], ["--help"]):
        print(f"usage: {DEPLOYMENT_RUNS_EXECUTE_USAGE}")
        print(
            "Drives runs from `yoke deployment-runs create` (which never "
            "executes) and resumes failed ones (--from-stage). The project "
            "checkout is resolved from the machine-config projects mapping "
            "for the active env; a stale mapping fails the lineage preflight "
            "with the resolved path named.\n\n"
            "--env names the CONTROL-PLANE env holding the run row, not the "
            "environment being deployed to. The target env is fixed on the "
            "run at create time (--target-env). One control plane usually "
            "serves every target, so a stage-targeted run and a "
            "production-targeted run are both driven through the same "
            "<control-plane>-db-admin env; the run output names both as "
            "release_control_plane=... target_env=..."
        )
        return 0
    active_env = os.environ.get(ENV_OVERRIDE, "").strip()
    if not active_env.endswith(DB_ADMIN_ENV_SUFFIX):
        print(
            "error: deployment-runs execute requires an explicit owner-only "
            "connection, for example `yoke --env prod-db-admin "
            "deployment-runs execute RUN-ID`",
            file=sys.stderr,
        )
        return 2

    completed = subprocess.run(
        [sys.executable, "-m", "yoke_core.domain.deploy_pipeline", *args],
        check=False,
    )
    return completed.returncode


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("deployment-runs", "execute"): deployment_runs_execute,
}

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke deployment-runs execute": DEPLOYMENT_RUNS_EXECUTE_USAGE,
}


__all__ = [
    "DEPLOYMENT_RUNS_EXECUTE_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "deployment_runs_execute",
]
