"""Keep the owning session live for one deployment-pipeline process."""

from __future__ import annotations

import os
import sys
from typing import List, Optional

from yoke_core.domain import deploy_pipeline
from yoke_core.domain.deploy_pipeline_control_plane import (
    DeploymentControlPlaneError,
    DriverLivenessPump,
    attach_driver,
    release_driver,
)
from yoke_core.domain.deploy_pipeline_pinned_source import (
    PINNED_RELEASE_ENV,
    PINNED_REEXEC_ENV,
    PINNED_SOURCE_ROOT_ENV,
)
from yoke_core.domain.deployment_run_driver_attachment import (
    PHASE_EXECUTING,
    PHASE_FREEZING_SOURCE,
)
from yoke_core.domain.session_liveness_pump import SessionLivenessPump

_ENGINE = "yoke_core.domain.deploy_pipeline_liveness_cli"


def _reexec_into_pinned_source(argv: List[str]) -> Optional[int]:
    """Freeze a self-deploy driver, then replace this process from that tree.

    The execute adapter must not import ``yoke_core`` — product CLI loads it
    at startup. The pin therefore lives in this engine process. ``os.execve``
    drops already-imported live-tree modules so the child loads the pin.
    """
    if os.environ.get(PINNED_REEXEC_ENV) == "1":
        return None
    if os.environ.get(PINNED_RELEASE_ENV) and os.environ.get(PINNED_SOURCE_ROOT_ENV):
        return None
    if not argv or not str(argv[0]).startswith("run-"):
        return None
    from yoke_core.domain.deploy_pipeline_pinned_source import (
        DeployPinnedSourceError,
    )
    from yoke_core.tools.deploy_pipeline_pinned_driver import (
        child_environment,
        frozen_driver_notice,
    )

    try:
        pinned = child_environment(argv[0])
    except DeployPinnedSourceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if not pinned:
        return None
    print(frozen_driver_notice(pinned))
    env = dict(pinned)
    env[PINNED_REEXEC_ENV] = "1"
    os.execve(sys.executable, [sys.executable, "-m", _ENGINE, *argv], env)
    return None


def _hold_driver(run_id: str, *, phase: str) -> None:
    attach_driver(run_id, phase=phase)


def _drop_driver(run_id: str) -> None:
    release_driver(run_id)


def main(argv: Optional[List[str]] = None) -> int:
    """Execute the deployment pipeline inside a bounded liveness scope."""
    argv = list(sys.argv[1:] if argv is None else argv)
    run_id = argv[0] if argv and str(argv[0]).startswith("run-") else ""
    held = False
    try:
        if run_id:
            try:
                _hold_driver(run_id, phase=PHASE_FREEZING_SOURCE)
                held = True
            except DeploymentControlPlaneError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            with DriverLivenessPump(run_id, phase=PHASE_FREEZING_SOURCE).running():
                refusal = _reexec_into_pinned_source(argv)
        else:
            refusal = _reexec_into_pinned_source(argv)
        if refusal is not None:
            return refusal
        if run_id:
            try:
                _hold_driver(run_id, phase=PHASE_EXECUTING)
                held = True
            except DeploymentControlPlaneError as exc:
                print(f"error: {exc}", file=sys.stderr)
                return 2
            with DriverLivenessPump(run_id, phase=PHASE_EXECUTING).running():
                return deploy_pipeline.main(argv)
        with SessionLivenessPump().running():
            return deploy_pipeline.main(argv)
    finally:
        if held and run_id:
            _drop_driver(run_id)


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main(list(sys.argv[1:])))


__all__ = ["main"]
