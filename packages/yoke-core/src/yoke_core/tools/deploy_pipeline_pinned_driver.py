"""Child-process env so a self-deploy driver loads the pinned tree."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping

from yoke_core.domain.deploy_pipeline_pinned_source import (
    PINNED_RELEASE_ENV,
    PINNED_SOURCE_ROOT_ENV,
    PinnedDriverSource,
    prepare_self_deploy_driver,
)
from yoke_core.tools._source_pythonpath import with_source_pythonpath


def environment_for_pinned_driver(
    prepared: PinnedDriverSource,
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """PYTHONPATH plus pin markers for a child executing *prepared*."""
    bound = with_source_pythonpath(env if env is not None else os.environ, prepared.root)
    bound[PINNED_RELEASE_ENV] = prepared.lineage
    bound[PINNED_SOURCE_ROOT_ENV] = str(prepared.root)
    return bound


def child_environment(run_id: str) -> dict[str, str] | None:
    """Env for the self-deploy engine child, or None on the relayed path."""
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
]
