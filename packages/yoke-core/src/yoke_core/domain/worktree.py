"""Worktree lifecycle front door.

Thin top-level surface for the worktree subsystem. Owns:

* re-exports of the public worktree API so
  ``from yoke_core.domain.worktree import resolve_main_root`` and sibling
  public imports remain the stable front door;
* the CLI dispatchers (``python3 -m yoke_core.domain.worktree
  {create,resolve,install,paths,playwright-cache}``) and the top-level
  ``main()`` entry point.

Heavy implementation lives in three responsibility-named siblings:

* :mod:`yoke_core.domain.worktree_paths` — repo / state / DB / named-path
  resolution. Also owns the low-level primitives (``_run``,
  ``_parse_item_id``) shared with the other siblings. Imported eagerly
  because it is the lightweight foundation every caller (including
  path-only readers like ``db_helpers.resolve_db_path()``) depends on.
* :mod:`yoke_core.domain.worktree_create` — ``create_worktree`` and provisioning
* :mod:`yoke_core.domain.worktree_deps` — dependency install + Playwright cache
* :mod:`yoke_core.domain.worktree_item_resolve` — DB-backed item-to-worktree lookup

Heavy siblings are deferred via PEP 562 ``__getattr__`` so the
``paths`` CLI and any other path-only reader can resolve the DB path
without importing provisioning code that might be broken mid-refactor.
Heavy-module attributes resolve on first access (or on the local
imports inside ``main_create`` / ``main_resolve`` / ``main_install`` /
``main_playwright_cache``).
"""

from __future__ import annotations

import importlib
import os
import sys
from typing import TYPE_CHECKING

# Lightweight resolver — always imported at module top.
from yoke_core.domain.worktree_paths import (
    _parse_item_id,
    is_git_worktree,
    resolve_db_path,
    resolve_main_root,
    resolve_named_path,
    resolve_yoke_root,
    resolve_worktree_root,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from yoke_core.domain.worktree_create import (
        CreateWorktreeResult,
        create_worktree,
    )
    from yoke_core.domain.worktree_deps import (
        DepInstallSpec,
        _find_nested,
        detect_deps,
        install_worktree_deps,
        resolve_playwright_cache,
    )
    from yoke_core.domain.worktree_item_resolve import (
        ResolvedWorktree,
        resolve_item_worktree,
    )

__all__ = [
    "CreateWorktreeResult",
    "DepInstallSpec",
    "ResolvedWorktree",
    "create_worktree",
    "detect_deps",
    "install_worktree_deps",
    "main",
    "main_create",
    "main_install",
    "main_paths",
    "main_playwright_cache",
    "main_resolve",
    "resolve_db_path",
    "resolve_item_worktree",
    "resolve_main_root",
    "resolve_named_path",
    "resolve_playwright_cache",
    "resolve_yoke_root",
    "resolve_worktree_root",
]


# Lazy attribute → module map for heavy siblings. PEP 562 ``__getattr__``
# defers the import until the attribute is actually accessed, so path-only
# callers never pay the cost (or risk) of importing provisioning code.
_LAZY_ATTRS = {
    "CreateWorktreeResult": "yoke_core.domain.worktree_create",
    "create_worktree": "yoke_core.domain.worktree_create",
    "DepInstallSpec": "yoke_core.domain.worktree_deps",
    "_find_nested": "yoke_core.domain.worktree_deps",
    "detect_deps": "yoke_core.domain.worktree_deps",
    "install_worktree_deps": "yoke_core.domain.worktree_deps",
    "resolve_playwright_cache": "yoke_core.domain.worktree_deps",
    "ResolvedWorktree": "yoke_core.domain.worktree_item_resolve",
    "resolve_item_worktree": "yoke_core.domain.worktree_item_resolve",
}


def __getattr__(name: str):
    module_name = _LAZY_ATTRS.get(name)
    if module_name is None:
        raise AttributeError(
            f"module 'yoke_core.domain.worktree' has no attribute {name!r}",
        )
    module = importlib.import_module(module_name)
    return getattr(module, name)


# ---------------------------------------------------------------------------
# CLI entry points
# ---------------------------------------------------------------------------

def main_create() -> int:
    """CLI entry point for ``create-worktree`` (``python3 -m yoke_core.domain.worktree create``)."""
    # Module-attribute lookup so the lazy ``__getattr__`` triggers the
    # real import on a clean miss, and tests that
    # ``monkeypatch.setattr(worktree, "create_worktree", ...)`` still
    # see their patch take effect inside this dispatcher.
    create_worktree = sys.modules[__name__].create_worktree

    args = sys.argv[2:]  # skip module path and subcommand
    if not args:
        print(
            "Usage: python3 -m yoke_core.domain.worktree create <id> "
            "[base-branch] [--project <project>]",
            file=sys.stderr,
        )
        return 1

    raw_id = args[0]
    item_num = _parse_item_id(raw_id)
    if item_num is None:
        print(f"Error: invalid item ID '{raw_id}'", file=sys.stderr)
        return 1

    project = None
    base_branch = None
    remaining = args[1:]
    i = 0
    positional = []
    while i < len(remaining):
        if remaining[i] == "--project" and i + 1 < len(remaining):
            project = remaining[i + 1]
            i += 2
        else:
            positional.append(remaining[i])
            i += 1

    if positional:
        base_branch = positional[0]

    repo_root = os.environ.get("YOKE_REPO_ROOT") or None
    result = create_worktree(
        item_num,
        base_branch=base_branch,
        project=project,
        repo_root=repo_root,
    )
    if result.error:
        print(f"Error: {result.error}", file=sys.stderr)
        return 1

    if len(result.worktrees) > 1:
        for entry in result.worktrees:
            print(entry.path)
    else:
        print(result.path)
    return 0


def main_resolve() -> int:
    """CLI entry point for ``resolve`` subcommand."""
    resolve_item_worktree = sys.modules[__name__].resolve_item_worktree

    args = sys.argv[2:]  # skip module path and subcommand
    if not args:
        print(
            "Usage: python3 -m yoke_core.domain.worktree resolve <YOK-N> "
            "[--field path|branch|repo|project|exists|scope|paths|branches|count|missing]",
            file=sys.stderr,
        )
        return 2

    item_ref = args[0]
    field = "path"
    i = 1
    while i < len(args):
        if args[i] == "--field" and i + 1 < len(args):
            field = args[i + 1]
            i += 2
        else:
            print(f"Error: unknown option '{args[i]}'", file=sys.stderr)
            return 2

    supported_fields = (
        "path", "branch", "repo", "project", "exists", "scope",
        "paths", "branches", "count", "missing",
    )
    if field not in supported_fields:
        print(f"Error: unsupported field '{field}'", file=sys.stderr)
        return 2

    try:
        result = resolve_item_worktree(item_ref)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2
    except LookupError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    item_num = _parse_item_id(item_ref)
    item_label = f"YOK-{item_num}" if item_num is not None else item_ref
    if field in ("path", "branch") and result.has_multiple:
        print(
            f"Error: {item_label} resolves to "
            f"{len(result.paths)} task worktrees; use --field "
            f"{'paths' if field == 'path' else 'branches'}",
            file=sys.stderr,
        )
        return 1

    if field == "path":
        print(result.path)
    elif field == "branch":
        print(result.branch)
    elif field == "repo":
        print(result.repo)
    elif field == "project":
        print(result.project)
    elif field == "exists":
        print("yes" if result.exists else "no")
    elif field == "scope":
        print(result.scope)
    elif field == "paths":
        print("\n".join(result.paths))
    elif field == "branches":
        print("\n".join(result.branches))
    elif field == "count":
        print(str(len(result.paths)))
    elif field == "missing":
        missing = [path for path in result.paths if not is_git_worktree(path)]
        print("\n".join(missing))

    return 0


def main_install() -> int:
    """CLI entry point for ``install`` subcommand."""
    install_worktree_deps = sys.modules[__name__].install_worktree_deps

    args = sys.argv[2:]  # skip module path and subcommand
    if not args:
        print("Usage: python3 -m yoke_core.domain.worktree install <worktree-path> [project-id]", file=sys.stderr)
        return 1

    worktree_path = args[0]
    project_id = args[1] if len(args) > 1 else None

    return install_worktree_deps(worktree_path, project_id)


def main_paths() -> int:
    """CLI entry point for ``paths`` subcommand."""
    args = sys.argv[2:]
    if not args:
        print("Usage: python3 -m yoke_core.domain.worktree paths <mode> [args]", file=sys.stderr)
        print(
            "Modes: main, worktree, main-file, yoke-root, db, config, config-example, backlog, board, docs, epics, ouroboros, designs, backups",
            file=sys.stderr,
        )
        return 1

    mode = args[0]
    rel_path = args[1] if len(args) > 1 else None
    try:
        resolved = resolve_named_path(mode, rel_path)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        print(
            "Modes: main, worktree, main-file, yoke-root, db, config, config-example, backlog, board, docs, epics, ouroboros, designs, backups",
            file=sys.stderr,
        )
        return 1
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(resolved)
    return 0


def main_playwright_cache() -> int:
    """CLI entry point for ``playwright-cache`` subcommand."""
    resolve_playwright_cache = sys.modules[__name__].resolve_playwright_cache

    args = sys.argv[2:]
    project_id = args[0] if args else None
    worktree_path = args[1] if len(args) > 1 else None
    resolved = resolve_playwright_cache(project_id, worktree_path)
    if resolved:
        print(resolved)
    return 0


def main() -> int:
    """Top-level CLI dispatcher."""
    if len(sys.argv) < 2:
        print(
            "Usage: python3 -m yoke_core.domain.worktree <create|resolve|install|paths|playwright-cache> ...",
            file=sys.stderr,
        )
        return 1

    subcmd = sys.argv[1]
    if subcmd == "create":
        return main_create()
    elif subcmd == "resolve":
        return main_resolve()
    elif subcmd == "install":
        return main_install()
    elif subcmd == "paths":
        return main_paths()
    elif subcmd == "playwright-cache":
        return main_playwright_cache()
    else:
        print(f"Error: unknown subcommand '{subcmd}'", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
