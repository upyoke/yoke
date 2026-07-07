"""Detect which code this CLI process runs: packaged wheel or source checkout.

The binding is a property of the running import, not of what exists on disk.
Cloning a Yoke source checkout activates nothing — the installed ``yoke``
keeps running its packaged wheels until an explicit step (``yoke dev setup``
with its editable install, or a worktree ``PYTHONPATH``) repoints the import.
This detector therefore reports where the ``yoke_cli`` package was actually
imported from:

* inside a checkout's ``packages/`` source tree → bound to that checkout,
* anywhere else (site-packages of a wheel install) → packaged wheel.

The import origin is preferred over ``.dist-info`` editable markers because
the dev-setup editable install swaps pip's path artifacts for a config-driven
shim (see :mod:`yoke_cli.config.editable_install`) and a worktree
``PYTHONPATH`` binds source without touching metadata — the origin is truthful
in every one of those shapes.

Vocabulary and checkout detection are shared with the ``status.run``
handler twin through :mod:`yoke_contracts.install_binding`.
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as package_version
from pathlib import Path
from typing import Any

import yoke_cli
from yoke_contracts.engine_version import (
    CLIENT_DISTRIBUTION_NAME as CLI_DISTRIBUTION_NAME,
)
from yoke_contracts.install_binding import (  # noqa: F401 - re-exported surface
    KIND_PACKAGED_WHEEL,
    KIND_SOURCE_CHECKOUT,
    label,
    source_checkout_root,
)


def detect(module_file: str | Path | None = None) -> dict[str, Any]:
    """Return the install binding of the running CLI.

    ``module_file`` defaults to the imported ``yoke_cli`` package's own file;
    tests inject synthetic paths to exercise both shapes.
    """

    resolved = Path(module_file if module_file is not None else yoke_cli.__file__)
    checkout_root = source_checkout_root(resolved)
    return {
        "kind": KIND_SOURCE_CHECKOUT if checkout_root else KIND_PACKAGED_WHEEL,
        "checkout_root": str(checkout_root) if checkout_root else None,
        "module_origin": str(resolved),
        "version": _distribution_version(),
    }


def _distribution_version() -> str:
    try:
        return package_version(CLI_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return ""


__all__ = [
    "CLI_DISTRIBUTION_NAME",
    "KIND_PACKAGED_WHEEL",
    "KIND_SOURCE_CHECKOUT",
    "detect",
    "label",
    "source_checkout_root",
]
