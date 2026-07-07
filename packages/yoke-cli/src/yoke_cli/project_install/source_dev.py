"""Source checkout detection for the explicit source-dev/admin branch.

Normal product installs must not import ``yoke_core`` or mutate Yoke
source-dev/admin wiring. This module keeps source checkout detection
client-safe and points operators at ``yoke dev setup`` for source-link
repair.
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from yoke_cli.project_install.files import (
    MODE_COPY,
    MODE_SOURCE_LINK,
    ProjectInstallError,
)
from yoke_contracts.install_binding import (
    is_yoke_source_checkout as _contract_is_yoke_source_checkout,
)


def is_yoke_source_checkout(root: Path) -> bool:
    """True iff *root* looks like the Yoke source checkout."""
    return _contract_is_yoke_source_checkout(root)


def resolve_mode(root: Path, explicit: Optional[str]) -> Tuple[str, str]:
    """Resolve product install mode without importing core."""
    is_source = is_yoke_source_checkout(root)
    if explicit == MODE_SOURCE_LINK or is_source:
        target = "this Yoke source checkout" if is_source else str(root)
        raise ProjectInstallError(
            f"source-link setup for {target} is owned by `yoke dev setup`; "
            "normal `yoke project install` always uses the product copy "
            "strategy for external project repos"
        )
    if explicit == MODE_COPY:
        return MODE_COPY, "explicit --copy"
    return MODE_COPY, "external project repo"


def install_source_link(
    repo_root: Path, *, operation: str = "install",
) -> Dict[str, Any]:
    """Delegate source-link repair to core when available."""
    try:
        module = importlib.import_module("yoke_core.domain.project_install_source_link")
    except ModuleNotFoundError as exc:
        raise ProjectInstallError(
            "source-link setup is a Yoke source-dev/admin operation and "
            "requires the yoke-core package. Normal product installs use "
            "HTTPS copy mode; run the explicit source-dev/admin setup from a "
            "Yoke source checkout."
        ) from exc
    return module.install_source_link(repo_root, operation=operation)


def source_link_uninstall_refusal(root: Path) -> ProjectInstallError:
    return ProjectInstallError(
        f"refusing to uninstall: {root} uses the source-link strategy. The "
        ".claude/.codex surfaces are git-tracked symlinks/source-dev files, "
        "not an installed product copy."
    )


__all__ = [
    "install_source_link",
    "is_yoke_source_checkout",
    "resolve_mode",
    "source_link_uninstall_refusal",
]
