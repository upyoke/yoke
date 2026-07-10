"""Config-driven editable path loader for a Yoke source checkout.

This module's *source text* is copied verbatim into site-packages as
``_yoke_editable_loader.py`` by :mod:`yoke_cli.config.editable_install` and run
by a one-line ``_yoke_editable.pth`` at every interpreter startup. It replaces
the absolute paths that setuptools bakes into an editable install (the default
that strands every import when the checkout is moved or renamed) with a root
that is resolved fresh each start from, in order:

  1. the ``YOKE_REPO_ROOT`` environment variable,
  2. the machine config (``~/.yoke/config.json``) — the first ``projects`` entry
     whose path is a Yoke source checkout,
  3. a fallback path recorded beside this file at install time.

Every candidate is validated as a real Yoke checkout before use, so a stale
candidate is skipped rather than adding a dead import path. After a checkout
move the machine config is the documented source of truth, so updating it (or
setting ``YOKE_REPO_ROOT``) makes imports resolve again with no reinstall.

Two safety properties matter because a ``.pth`` line runs inside every
interpreter start:

  * **Never raises.** :func:`install_into_sys_path` swallows all exceptions; a
    resolution failure adds nothing and imports fail later with an ordinary
    ``ModuleNotFoundError`` instead of aborting interpreter startup.
  * **Appends, never inserts.** An explicit ``PYTHONPATH`` (e.g. a linked
    worktree's source, or the ``watch_pytest`` self-binding) still wins.

Kept import-free of ``yoke_*`` on purpose: it runs before those packages are on
``sys.path``. The config-path precedence mirrors
:mod:`yoke_cli.config.machine_config` but cannot import it for the same reason.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

YOKE_REPO_ROOT_ENV = "YOKE_REPO_ROOT"
MACHINE_CONFIG_ENV = "YOKE_MACHINE_CONFIG_FILE"
MACHINE_HOME_ENV = "YOKE_MACHINE_HOME"
CONFIG_FILE_NAME = "config.json"
FALLBACK_SIDECAR_NAME = "_yoke_editable_root.txt"

# Checkout-relative source roots for the four packages, in dependency order. The
# repo root itself is appended after them so the top-level ``runtime`` package
# imports. This tuple is the single place the package layout is encoded.
RELATIVE_SRC_DIRS = (
    "packages/yoke-contracts/src",
    "packages/yoke-cli/src",
    "packages/yoke-harness/src",
    "packages/yoke-core/src",
)

# Structural proof that a root is a Yoke source checkout whose editable source
# actually exists: the core package importable from packages/yoke-core/src.
_CHECKOUT_MARKER = "packages/yoke-core/src/yoke_core/__init__.py"


def _is_yoke_checkout(root: Path) -> bool:
    try:
        return (Path(root) / _CHECKOUT_MARKER).is_file()
    except OSError:
        return False


def _default_config_path(environ) -> Path:
    override = environ.get(MACHINE_CONFIG_ENV, "").strip()
    home = environ.get(MACHINE_HOME_ENV, "").strip()
    base = Path(home).expanduser() if home else Path.home() / ".yoke"
    if override:
        path = Path(override).expanduser()
        return path if path.is_absolute() else base / path
    return base / CONFIG_FILE_NAME


def _root_from_config(config_path: Path):
    try:
        data = json.loads(Path(config_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    projects = data.get("projects") if isinstance(data, dict) else None
    # projects is a flat list of {checkout, ...} entries; the legacy
    # checkout-keyed object is still tolerated. Standalone shim — no yoke
    # imports available, so both shapes are unpacked inline.
    if isinstance(projects, list):
        checkouts = [e.get("checkout") for e in projects if isinstance(e, dict)]
    elif isinstance(projects, dict):
        checkouts = list(projects.keys())
    else:
        return None
    # Sorted for deterministic selection when more than one checkout qualifies.
    for key in sorted(c for c in checkouts if isinstance(c, str) and c.strip()):
        candidate = Path(str(key)).expanduser()
        if _is_yoke_checkout(candidate):
            return candidate
    return None


def _fallback_root():
    try:
        text = Path(__file__).with_name(FALLBACK_SIDECAR_NAME).read_text(
            encoding="utf-8"
        )
    except (OSError, ValueError):
        return None
    candidate = Path(text.strip()).expanduser()
    return candidate if _is_yoke_checkout(candidate) else None


def resolve_repo_root(environ=None, config_path=None):
    """Return the Yoke checkout root for this machine, or ``None``.

    Resolution order: ``YOKE_REPO_ROOT`` → machine config → install-time
    fallback. Every source is validated with :func:`_is_yoke_checkout`, so a
    stale value is skipped instead of returned.
    """

    environ = os.environ if environ is None else environ
    explicit = environ.get(YOKE_REPO_ROOT_ENV, "").strip()
    if explicit:
        candidate = Path(explicit).expanduser()
        if _is_yoke_checkout(candidate):
            return candidate
    resolved = _root_from_config(
        Path(config_path) if config_path is not None
        else _default_config_path(environ)
    )
    if resolved is not None:
        return resolved
    return _fallback_root()


def editable_paths(repo_root):
    """Return existing ``sys.path`` entries for *repo_root*: src dirs then root."""

    root = Path(repo_root)
    candidates = [root / rel for rel in RELATIVE_SRC_DIRS]
    candidates.append(root)
    return [str(path) for path in candidates if path.is_dir()]


def install_into_sys_path(environ=None, config_path=None):
    """Append the checkout's editable source dirs to ``sys.path``.

    Returns the list of entries added. Never raises: a ``.pth`` line runs inside
    interpreter startup, so any failure must degrade to "add nothing" rather
    than abort every Python process on this machine.
    """

    try:
        root = resolve_repo_root(environ, config_path)
        if root is None:
            return []
        added = []
        for entry in editable_paths(root):
            if entry not in sys.path:
                sys.path.append(entry)
                added.append(entry)
        return added
    except Exception:
        return []
