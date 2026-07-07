"""Install a config-driven editable path shim into site-packages.

``pip install -e`` wires a Yoke source checkout onto ``sys.path`` by baking the
checkout's *absolute* path into site-packages — five ``__editable__.*.pth``
files plus a ``__editable___*_finder.py`` for the top-level ``runtime`` package.
Those artifacts strand every import when the checkout is moved or renamed (the
rename that motivated this shim), forcing a reinstall.

:func:`swap_to_config_driven` keeps everything pip does that is *not* path
wiring — dependency resolution, the ``yoke`` console script, ``.dist-info``
metadata — and replaces only the brittle path artifacts with:

  * ``_yoke_editable_loader.py`` — a verbatim copy of
    :mod:`yoke_cli.config._editable_loader_template`, which resolves the repo
    root at each interpreter start from ``YOKE_REPO_ROOT`` / machine config /
    an install-time fallback,
  * ``_yoke_editable_root.txt`` — the install-time fallback root, and
  * ``_yoke_editable.pth`` — a one-line loader invocation.

After this swap, moving the checkout and updating machine config (the documented
move step) makes imports resolve again with no reinstall.
"""

from __future__ import annotations

import sysconfig
from pathlib import Path
from typing import Any

from yoke_cli.config import _editable_loader_template as loader_template

LOADER_MODULE_NAME = "_yoke_editable_loader"
LOADER_FILE_NAME = f"{LOADER_MODULE_NAME}.py"
PTH_FILE_NAME = "_yoke_editable.pth"
SIDECAR_FILE_NAME = loader_template.FALLBACK_SIDECAR_NAME
PTH_CONTENT = f"import {LOADER_MODULE_NAME}; {LOADER_MODULE_NAME}.install_into_sys_path()\n"

# setuptools editable artifacts for the Yoke distributions (never buzz/etc.):
# `__editable__.yoke*.pth` covers the meta package and the four sub-packages;
# `__editable___yoke*_finder.py` covers any strict-mode import finder.
_STALE_ARTIFACT_GLOBS = ("__editable__.yoke*.pth", "__editable___yoke*_finder.py")


def loader_source() -> str:
    """Return the verbatim source of the loader template.

    Copied byte-for-byte into site-packages so the installed loader can never
    drift from the tested module.
    """

    return Path(loader_template.__file__).read_text(encoding="utf-8")


def site_packages_dir() -> Path:
    """The current interpreter's site-packages (where pip installs editables)."""

    return Path(sysconfig.get_paths()["purelib"])


def stale_pip_artifacts(site_dir: Path) -> list[Path]:
    """Return the setuptools editable path artifacts for the Yoke distributions."""

    site_dir = Path(site_dir)
    found: list[Path] = []
    for pattern in _STALE_ARTIFACT_GLOBS:
        found.extend(sorted(site_dir.glob(pattern)))
    return found


def swap_to_config_driven(
    site_dir: Path, *, repo_root: Path, loader_source_text: str | None = None,
) -> dict[str, Any]:
    """Replace pip's hardcoded editable artifacts with the config-driven shim.

    Idempotent: removes any prior shim files and stale pip artifacts, then writes
    the loader, its fallback sidecar, and the ``.pth``.

    ``loader_source_text`` supplies the loader template content directly. Pass it
    when the editable install being swapped just uninstalled the product wheel
    this process imported the template from — reading it afterwards via
    :func:`loader_source` would hit a now-deleted file.
    """

    site_dir = Path(site_dir)
    repo_root = Path(repo_root).expanduser().resolve()
    site_dir.mkdir(parents=True, exist_ok=True)

    removed = [str(path) for path in stale_pip_artifacts(site_dir)]
    for path in stale_pip_artifacts(site_dir):
        path.unlink()

    loader_path = site_dir / LOADER_FILE_NAME
    sidecar_path = site_dir / SIDECAR_FILE_NAME
    pth_path = site_dir / PTH_FILE_NAME
    loader_path.write_text(
        loader_source_text if loader_source_text is not None else loader_source(),
        encoding="utf-8",
    )
    sidecar_path.write_text(str(repo_root) + "\n", encoding="utf-8")
    pth_path.write_text(PTH_CONTENT, encoding="utf-8")

    return {
        "site_dir": str(site_dir),
        "repo_root": str(repo_root),
        "removed": removed,
        "written": [str(loader_path), str(sidecar_path), str(pth_path)],
    }


__all__ = [
    "LOADER_MODULE_NAME",
    "PTH_CONTENT",
    "loader_source",
    "site_packages_dir",
    "stale_pip_artifacts",
    "swap_to_config_driven",
]
