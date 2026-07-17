"""Client-local deployment-run executor.

The run record belongs to an owner-only Postgres connection while GitHub App
operations relay through that connection's HTTPS sibling. Keeping this as a
tool-shaped command gives operators one stable installed entrypoint instead
of requiring a source checkout, an editable import, and two coordinated
environment variables.
"""

from __future__ import annotations

import os
import sys
from typing import Callable, Dict, List, Tuple
from yoke_contracts.machine_config.schema import (
    DB_ADMIN_ENV_SUFFIX,
    ENV_OVERRIDE,
)


AdapterFn = Callable[[List[str]], int]
DEPLOYMENT_RUNS_EXECUTE_USAGE = (
    "yoke --env ENV-db-admin deployment-runs execute RUN-ID "
    "[--timeout MIN] [--from-stage STAGE] [--fresh] "
    "[--product-repo-path PATH] [--image-tag TAG]"
)


def deployment_runs_execute(args: List[str]) -> int:
    """Execute or resume a run through the selected admin connection."""
    active_env = os.environ.get(ENV_OVERRIDE, "").strip()
    if not active_env.endswith(DB_ADMIN_ENV_SUFFIX):
        print(
            "error: deployment-runs execute requires an explicit owner-only "
            "connection, for example `yoke --env prod-db-admin "
            "deployment-runs execute RUN-ID`",
            file=sys.stderr,
        )
        return 2

    from yoke_core.domain.deploy_pipeline import main as deploy_pipeline_main

    return deploy_pipeline_main(args)


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
