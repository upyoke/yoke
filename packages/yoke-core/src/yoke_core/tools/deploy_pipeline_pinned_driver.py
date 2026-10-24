"""Child-process env so a self-release driver loads the pinned tree."""

from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Mapping

from yoke_contracts.refusal_recovery import compose_refusal
from yoke_contracts.uv_project import UV_EXECUTABLE, is_uv_project

from yoke_core.domain.deploy_pipeline_pinned_source import (
    PINNED_RELEASE_ENV,
    PINNED_SOURCE_ROOT_ENV,
    DeployPinnedSourceError,
    PinnedDriverSource,
    prepare_self_deploy_driver,
)
from yoke_core.tools._source_pythonpath import with_source_pythonpath


def environment_for_pinned_driver(
    prepared: PinnedDriverSource,
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Sync the pin's runtime dependencies and bind its child interpreter."""
    root = prepared.root
    prefix = root / ".venv"
    recovery = (
        f"Run `uv sync --frozen --no-dev --project {shlex.quote(str(root))}` "
        "with UV_PROJECT_ENVIRONMENT unset, then re-drive the same run."
    )

    def refuse(detail: str) -> None:
        raise DeployPinnedSourceError(
            compose_refusal(
                f"DEPLOY-DRIVER-ENVIRONMENT: {detail}.", recovery=f"{recovery}"
            )
        )

    if not is_uv_project(root):
        refuse(
            f"pinned checkout {root} lacks pyproject.toml or uv.lock; restore the pin"
        )
    if prefix.is_symlink():
        refuse(f"{prefix} is a symlink; replace it with a local environment")
    bound = {
        key: value
        for key, value in (env if env is not None else os.environ).items()
        if not key.startswith("UV_") and key not in {"PYTHONHOME", "VIRTUAL_ENV"}
    }
    bound["UV_PROJECT_ENVIRONMENT"] = str(prefix)
    try:
        completed = subprocess.run(
            [UV_EXECUTABLE, "sync", "--frozen", "--no-dev", "--project", str(root)],
            cwd=root,
            env=bound,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
    except FileNotFoundError:
        refuse("uv is unavailable; install uv and ensure it is on the driver's PATH")
    except (OSError, subprocess.TimeoutExpired) as exc:
        refuse(f"locked environment preparation failed ({type(exc).__name__})")
    if completed.returncode:
        refuse(
            f"locked environment sync exited {completed.returncode}: "
            f"{completed.stderr.strip()}"
        )
    python = prefix / ("Scripts/python.exe" if os.name == "nt" else "bin/python3")
    if not python.is_file():
        refuse(f"locked environment has no interpreter at {python}")
    bound["VIRTUAL_ENV"] = str(prefix)
    bound["PATH"] = str(python.parent) + os.pathsep + bound.get("PATH", "")
    bound = with_source_pythonpath(bound, root)
    bound[PINNED_RELEASE_ENV] = prepared.lineage
    bound[PINNED_SOURCE_ROOT_ENV] = str(prepared.root)
    return bound


def pinned_driver_command(
    module: str, argv: list[str], env: Mapping[str, str] | None
) -> list[str]:
    """Use the prepared checkout Python, or the installed engine."""
    root = (env or {}).get(PINNED_SOURCE_ROOT_ENV)
    python = (
        str(
            Path(root)
            / ".venv"
            / ("Scripts/python.exe" if os.name == "nt" else "bin/python3")
        )
        if root
        else sys.executable
    )
    return [python, "-m", module, *argv]


def child_environment(run_id: str) -> dict[str, str] | None:
    """Env for the self-release engine child, or None for the installed engine."""
    prepared = prepare_self_deploy_driver(run_id)
    if prepared is None:
        return None
    return environment_for_pinned_driver(prepared)


def frozen_driver_notice(env: Mapping[str, str]) -> str:
    """One-line progress record that the child is pinned."""
    lineage = env.get(PINNED_RELEASE_ENV, "")
    root = env.get(PINNED_SOURCE_ROOT_ENV, "")
    return f"Self-deploy driver frozen at {lineage} ({root})"


def pinned_driver_cwd(env: Mapping[str, str] | None) -> str | None:
    root = (env or {}).get(PINNED_SOURCE_ROOT_ENV, "").strip()
    return root if root and Path(root).is_dir() else None


__all__ = [
    "child_environment",
    "environment_for_pinned_driver",
    "frozen_driver_notice",
    "pinned_driver_cwd",
    "pinned_driver_command",
]
