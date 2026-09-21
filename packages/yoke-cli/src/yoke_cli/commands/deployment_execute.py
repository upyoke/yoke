"""Client-local deployment-run executor."""

from __future__ import annotations

import subprocess
import sys
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands.adapters.deployment_execution_authority import (
    execution_connection_error,
)
from yoke_contracts.deployment_itemless_teaching import (
    INTERRUPTED_RUN_RECOVERY,
)

AdapterFn = Callable[[List[str]], int]
DEPLOYMENT_RUNS_EXECUTE_USAGE = (
    "yoke --env CONTROL-PLANE-ENV deployment-runs execute RUN-ID "
    "[--timeout MIN] [--from-stage STAGE] [--fresh] "
    "[--product-repo-path PATH --image-tag TAG]"
)


def deployment_runs_execute(args: List[str]) -> int:
    """Execute or resume a run through the selected control plane."""
    if args in (["-h"], ["--help"]):
        print(f"usage: {DEPLOYMENT_RUNS_EXECUTE_USAGE}")
        print(
            "Drives runs from `yoke deployment-runs create` (which never "
            "executes) and resumes failed ones (--from-stage). A failed "
            "same-run --from-stage resume re-enters executing at that stage "
            "and does not replay skipped completed stages. The project "
            "checkout is resolved from the machine-config projects mapping "
            "for the active env; a stale mapping fails the lineage preflight "
            "with the resolved path named.\n\n"
            "--product-repo-path applies only to an ITEMLESS environment "
            "deploy and requires --image-tag, which is why the two are shown "
            "together. A run carrying items resolves its product source from "
            "those items, so passing the flag there is refused rather than "
            "ignored: it would otherwise read as having pinned a checkout "
            "that the run never consulted.\n\n"
            "--env names the CONTROL-PLANE holding the run row, not the "
            "environment being deployed to. The target environment is fixed "
            "on the run at create time (--environment overrides the flow's "
            "registered target). One control plane usually serves every "
            "target, so a stage-targeted run and a prod-targeted run are "
            "both driven through the same control-plane env; the "
            "run output names both as release_control_plane=... target=...\n\n"
            "Ordinary external delivery works over HTTPS. A serving-API "
            "self-deploy is refused on HTTPS and names the paired local "
            "*-db-admin connection that keeps run state writable while the "
            "API is replaced. That self-deploy freezes the driver at the "
            "run's release_lineage so a merge landing mid-run cannot mix "
            "source; a named halt stays re-drivable. The driver records "
            "itself on the run before that freeze, so a second execute of "
            "the same run refuses by naming the live session, pid, phase, "
            "and capture. watch_tail consults that fact before blaming "
            "missing capture flags. Steering does not treat a created run "
            "with a live driver as waiting to be driven.\n\n"
            f"{INTERRUPTED_RUN_RECOVERY}"
        )
        return 0
    if not args or not args[0].startswith("run-"):
        print("error: deployment-runs execute requires RUN-ID", file=sys.stderr)
        return 2
    if refusal := execution_connection_error(args[0]):
        print(f"error: {refusal}", file=sys.stderr)
        return 2

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "yoke_core.domain.deploy_pipeline_liveness_cli",
            *args,
        ],
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
