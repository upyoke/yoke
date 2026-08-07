"""Derive Atlas currency trigger paths from integrity collector inputs.

The pre-commit gate refreshes ``docs/atlas.md`` only when staged paths
intersect this set. Paths come from the modules the inventory collectors
import — package trees and sibling ``registry*`` /
``operation_inventory*`` files — not a hand-maintained absolute list.

Installed modules may resolve from a different checkout than the git
toplevel (editable install on main while committing in a worktree), so
paths are reconstructed from the ``yoke_core`` / ``yoke_cli`` package
layout rather than ``Path.relative_to(target_root)``.
"""

from __future__ import annotations

from pathlib import Path
from types import ModuleType
from typing import Iterable


_PACKAGE_REPO_PREFIX = {
    "yoke_core": "packages/yoke-core/src/",
    "yoke_cli": "packages/yoke-cli/src/",
}


def _repo_rel_from_installed(file_path: Path) -> str | None:
    parts = file_path.resolve().parts
    for pkg, prefix in _PACKAGE_REPO_PREFIX.items():
        if pkg not in parts:
            continue
        idx = parts.index(pkg)
        return prefix + "/".join(parts[idx:])
    return None


def _files_under_installed(root: Path, *, pattern: str) -> set[str]:
    paths: set[str] = set()
    if not root.is_dir():
        return paths
    for py in root.glob(pattern):
        if not py.is_file():
            continue
        rel = _repo_rel_from_installed(py)
        if rel:
            paths.add(rel)
    return paths


def _module_tree_paths(module: ModuleType) -> set[str]:
    paths: set[str] = set()
    file = getattr(module, "__file__", None)
    if file:
        rel = _repo_rel_from_installed(Path(file))
        if rel:
            paths.add(rel)
    for entry in getattr(module, "__path__", ()) or ():
        paths |= _files_under_installed(Path(entry), pattern="**/*.py")
    return paths


def _sibling_glob_paths(module: ModuleType, pattern: str) -> set[str]:
    file = getattr(module, "__file__", None)
    if not file:
        return set()
    return _files_under_installed(Path(file).resolve().parent, pattern=pattern)


def _collector_modules() -> Iterable[ModuleType]:
    """Import the same modules the three inventory collectors read."""
    from yoke_cli import operation_inventory
    from yoke_cli.commands import flag_adapters
    from yoke_cli.commands import registry as cli_registry
    from yoke_core.domain import handlers as handlers_pkg
    from yoke_core.domain import yoke_function_dispatch
    from yoke_core.domain import yoke_function_registry

    return (
        handlers_pkg,
        yoke_function_dispatch,
        yoke_function_registry,
        cli_registry,
        flag_adapters,
        operation_inventory,
    )


def currency_trigger_paths(target_root: Path | None = None) -> frozenset[str]:
    """Repo-relative paths whose edits can stale Atlas inventory sections.

    ``target_root`` is accepted for call-site symmetry with other Atlas
    helpers; derivation does not read the tree (modules are imported).
    """
    del target_root  # layout-derived; see module docstring
    paths: set[str] = set()
    for module in _collector_modules():
        paths |= _module_tree_paths(module)
    from yoke_cli import operation_inventory
    from yoke_cli.commands import registry as cli_registry

    paths |= _sibling_glob_paths(cli_registry, "registry*.py")
    paths |= _sibling_glob_paths(cli_registry, "flag_adapter*.py")
    paths |= _sibling_glob_paths(operation_inventory, "operation_inventory*.py")
    return frozenset(paths)


def staged_touches_currency_inputs(
    target_root: Path | None,
    staged_paths: Iterable[str],
) -> bool:
    """True when any staged path is an Atlas currency input."""
    triggers = currency_trigger_paths(target_root)
    for path in staged_paths:
        normalised = path.replace("\\", "/")
        if normalised in triggers:
            return True
    return False


__all__ = [
    "currency_trigger_paths",
    "staged_touches_currency_inputs",
]
