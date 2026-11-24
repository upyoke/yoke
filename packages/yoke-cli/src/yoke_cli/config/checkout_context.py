"""Client-side checkout context helpers."""

from __future__ import annotations

import os
from typing import Optional

from yoke_contracts.machine_config.checkout import find_main_checkout


def resolve_repo_root_from_cwd(cwd: str | None = None) -> Optional[str]:
    """Return the owning main repo root for the caller's cwd, if any."""

    selected = cwd or os.environ.get("YOKE_RESOLVE_CWD") or os.getcwd()
    root = find_main_checkout(selected)
    return str(root) if root is not None else None


__all__ = ["resolve_repo_root_from_cwd"]
