"""Smart detection of an existing local Yoke source checkout.

The "Develop Yoke itself" flow prefers an existing checkout over cloning. It
looks in two places: the source path of the running ``yoke`` install (an
editable/source install points its package at the repo), and a small set of
common checkout directories. A candidate counts only when it is a Yoke source
checkout whose ``origin`` remote points at Yoke's GitHub repo, so a same-named
unrelated repo is never adopted.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yoke_cli
from yoke_cli.config import project_git_prerequisite
from yoke_cli.config.yoke_dev_access import YOKE_GITHUB_REPO
from yoke_cli.project_install import source_dev

# Common places a contributor keeps their Yoke checkout, in preference order.
# ~/code/yoke leads to match the default checkout folder the wizard proposes.
_COMMON_CHECKOUT_DIRS = ("~/code/yoke", "~/yoke", "~/dev/yoke")


def _origin_url(root: Path) -> str:
    project_git_prerequisite.require_git_available()
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def origin_is_yoke(root: Path) -> bool:
    """True when ``root``'s git ``origin`` points at Yoke's GitHub repo.

    Matches both HTTPS (``…/upyoke/yoke(.git)``) and SSH
    (``git@github.com:upyoke/yoke(.git)``) origin forms.
    """
    url = _origin_url(root)
    if not url:
        return False
    normalized = url.removesuffix(".git")
    return normalized.endswith("/" + YOKE_GITHUB_REPO) or normalized.endswith(
        ":" + YOKE_GITHUB_REPO
    )


def _is_adoptable_checkout(root: Path) -> bool:
    return (
        root.is_dir()
        and source_dev.is_yoke_source_checkout(root)
        and origin_is_yoke(root)
    )


def _install_source_root() -> Path | None:
    """Walk up from the running ``yoke`` package to its repo root, if any.

    An editable/source install leaves ``yoke_cli`` inside the repo tree; the
    repo root is the first ancestor that reads as a Yoke source checkout. A
    wheel install lives under ``site-packages`` and yields no Yoke root.
    """
    start = Path(yoke_cli.__file__).resolve().parent
    for candidate in (start, *start.parents):
        if source_dev.is_yoke_source_checkout(candidate):
            return candidate
    return None


def detect_yoke_checkouts() -> list[Path]:
    """Return every distinct adoptable Yoke checkout found on this machine.

    The running install's source root (when editable) leads, then the common
    checkout dirs. Duplicates (the same resolved path reached two ways) collapse
    so the picker never shows one checkout twice. An empty list means the flow
    should offer to clone instead.
    """
    found: list[Path] = []
    seen: set[Path] = set()

    def _add(root: Path | None) -> None:
        if root is None:
            return
        resolved = root.resolve()
        if resolved in seen or not _is_adoptable_checkout(resolved):
            return
        seen.add(resolved)
        found.append(resolved)

    _add(_install_source_root())
    for raw in _COMMON_CHECKOUT_DIRS:
        _add(Path(raw).expanduser())
    return found


def preflight_dev_checkout(checkout: str) -> str | None:
    """Return a recoverable error for an invalid source-dev checkout target."""
    path = Path(checkout).expanduser()
    if not path.exists():
        return None
    if not path.is_dir():
        return (
            f"{path} exists but is not a folder. Choose an empty folder to "
            "clone Yoke into, or point at an existing Yoke clone."
        )
    try:
        non_empty = any(path.iterdir())
    except OSError as exc:
        return f"Couldn't inspect {path}: {exc}"
    if not non_empty or source_dev.is_yoke_source_checkout(path):
        return None
    return (
        f"{path} already has files, but it is not a Yoke source checkout. "
        "Choose an empty folder to clone Yoke into, or point at an existing "
        "Yoke clone."
    )


__all__ = [
    "detect_yoke_checkouts",
    "origin_is_yoke",
    "preflight_dev_checkout",
]
