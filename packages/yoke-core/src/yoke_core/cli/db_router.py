"""Unified DB router — the canonical Python CLI surface for the Yoke DB.

Operators invoke::

    python3 -m yoke_core.cli.db_router <domain> <subcommand> [args...]

The router provides:

* **Explicit bootstrap only** — schema/domain auto-init runs when the
  operator invokes the ``init`` subcommand or when
  ``YOKE_DB_INIT_ALLOW=1`` opts the process in (tests, first-time
  bootstrap, cross-worktree DB creation).  Normal runtime commands
  (reads, writes, domain dispatch) never trigger hidden schema
  bootstrap.  ``YOKE_DB_INIT_DONE=1`` still short-circuits the init
  path within a process for callers that intentionally piggyback on
  another init run.
* **Missing-schema remediation** — when a runtime command runs against
  an existing DB whose baseline schema is incomplete, the router
  refuses the command and prints concrete remediation pointing at
  ``db_router init``.  No silent ``CREATE TABLE`` as a side effect of a
  read-looking command.
* **Domain dispatch** — delegates to the canonical Python domain module
  for each domain by importing and calling its ``main(argv)`` function,
  avoiding per-call subprocess overhead.
* **Items subcommands** — read subcommands (``get``, ``list``, ``count``,
  ``row``, ``progress``) route to :mod:`yoke_core.domain.query_items_cli`
  in-process; write subcommands route to the Python-owned
  ``service_client backlog-cli`` parser in-process.
* **Merge dispatch** — ``merge run …`` delegates to
  :mod:`yoke_core.engines.merge_worktree`.
* **Query escape hatch** — ``query [-separator S] "<SQL>"`` routes to
  :mod:`yoke_core.cli.raw_query`.
* **Help** — prints the same domain list / subcommand hint structure the
  shell router printed.

This module is the canonical DB-router surface referenced by the
file-layout rule in ``AGENTS.md``. The bulk of the implementation is
split across responsibility-named siblings:

* :mod:`yoke_core.cli.db_router_init` — bootstrap and schema gate
* :mod:`yoke_core.cli.db_router_dispatch` — dispatch tables + helpers
* :mod:`yoke_core.cli.db_router_help` — usage and domain help text

Path resolution (``_repo_root`` / ``_strip_worktree_prefix``) and the
top-level ``main()`` entry stay
in this module so monkey-patches against ``db_router.__file__`` and the
``_dispatch_python_module`` binding continue to take effect inside
``main()`` — Python looks up free names through the module the function
was defined in, not the module it was re-exported from.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional

from yoke_core.api.repo_root import find_repo_root
from yoke_core.cli.db_router_dispatch import (  # noqa: F401
    _DOMAIN_PY_MODULES,
    _ITEMS_READ_SUBCMDS,
    _ITEMS_WRITE_SUBCMDS,
    _dispatch_module_function,
    _dispatch_python_module,
)
from yoke_core.cli.db_router_help import _print_domain_help, _print_usage  # noqa: F401
from yoke_core.cli.db_router_suggestions import emit_unknown_domain_hint, emit_unknown_domain_subcmd_hint, emit_unknown_items_subcmd_hint
from yoke_core.cli.db_router_init import (  # noqa: F401
    _AUTO_INIT_MODULES,
    _connected_postgres_authority_active,
    _INIT_ALLOW_ENV,
    _INIT_DONE_ENV,
    _dispatch_items_get_section,
    _init_allowed,
    _probe_schema_or_remediate,
    _run_init_modules,
)


# Path / env resolution — kept inline for ``__file__`` monkey-patch tests.

def _strip_worktree_prefix(path: Path) -> Path:
    """Strip ``.worktrees/<branch>/`` from *path* to get the main repo root."""
    parts = path.parts
    for i, part in enumerate(parts):
        if part == ".worktrees" and i + 1 < len(parts):
            return Path(*parts[:i]) if i > 0 else Path("/")
    return path


def _repo_root() -> Path:
    """Resolve the **main** repo root by walking up from this file."""
    here = Path(__file__).resolve()
    try:
        found = find_repo_root(here)
        guess = _strip_worktree_prefix(found) if _is_under_root(here, found) else _repo_root_from_layout(here)
    except RuntimeError:
        guess = _repo_root_from_layout(here)
    if _looks_like_repo_root(guess):
        return guess
    env_root = os.environ.get("YOKE_REPO_ROOT")
    if env_root:
        env_path = Path(env_root).resolve()
        if _looks_like_repo_root(env_path):
            return env_path
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        git_root = _strip_worktree_prefix(Path(result.stdout.strip()))
        if _looks_like_repo_root(git_root):
            return git_root
    except (subprocess.CalledProcessError, FileNotFoundError):
        pass
    return guess


def _repo_root_from_layout(here: Path) -> Path:
    for candidate in (here.parent, *here.parents):
        for root in (_strip_worktree_prefix(candidate), candidate):
            if _looks_like_repo_root(root):
                return root
    return _strip_worktree_prefix(here.parent)


def _is_under_root(path: Path, root: Path) -> bool:
    return path == root or root in path.parents


def _looks_like_repo_root(path: Path) -> bool:
    return (path / "packages" / "yoke-core").is_dir() or (path / "runtime" / "api").is_dir()


# Auto-init gate — kept inline for ``_run_init_modules`` monkey-patch tests.

def _auto_init(repo_root: Path, *, forced: bool = False) -> None:
    """Schema/domain bootstrap gate.

    With hardened semantics, the module chain runs only when one of
    the following is true:

    1. ``forced=True`` — caller invoked the explicit ``init``
       subcommand (or an equivalent bootstrap surface).
    2. ``YOKE_DB_INIT_ALLOW=1`` — test fixtures or bootstrap workflows
       opted the process in.

    Otherwise, this function returns immediately and the normal runtime
    command path must handle any missing-schema condition via
    :func:`_probe_schema_or_remediate` — the router refuses the command
    with a concrete remediation message rather than silently creating
    schema as a side effect.
    """
    if os.environ.get(_INIT_DONE_ENV) == "1":
        return

    yoke_db = os.environ.get("YOKE_DB")
    if yoke_db and not Path(yoke_db).exists():
        try:
            requested = Path(yoke_db).expanduser().resolve(strict=False)
            retired = (repo_root / "data" / "yoke.db").resolve(strict=False)
        except OSError:
            requested = retired = None
        if requested == retired and _connected_postgres_authority_active(repo_root):
            os.environ[_INIT_DONE_ENV] = "1"
            return
        if not forced and not _init_allowed():
            print(
                f"Warning: YOKE_DB is set to '{yoke_db}' but the file does not exist.",
                file=sys.stderr,
            )
            print(
                "  Auto-init skipped — normal runtime commands no longer bootstrap schema.",
                file=sys.stderr,
            )
            print(
                "  To create a DB at this path intentionally, run:",
                file=sys.stderr,
            )
            print(
                "    python3 -m yoke_core.cli.db_router init",
                file=sys.stderr,
            )
            print(
                f"  Or set {_INIT_ALLOW_ENV}=1 to opt the current process "
                "into ambient bootstrap (tests, first-run provisioning).",
                file=sys.stderr,
            )
            os.environ[_INIT_DONE_ENV] = "1"
            return

    if not forced and not _init_allowed():
        os.environ[_INIT_DONE_ENV] = "1"
        return

    _run_init_modules(repo_root)


# Shared public-ref normalization for delegated domains. Canonical parser:
# ``yoke_core.domain.yok_n_parser``. Helper rewrites a PREFIX-N token at
# the configured positional index for known (domain, subcommand) pairs
# so downstream surfaces see a bare integer. Falls through unchanged on
# any parse failure — downstream diagnostics stay the single error path.

_DOMAIN_YOK_N_NORMALIZE: Dict[str, Dict[str, int]] = {
    "sections": {"upsert": 0, "get": 0, "list": 0, "delete": 0},
    "designs":  {"render": 0, "list": 0, "show": 0},
    "runs":     {"start-for-item": 0},
}


def _normalize_yok_n_arg(domain: str, remaining: List[str]) -> List[str]:
    spec = _DOMAIN_YOK_N_NORMALIZE.get(domain)
    if not spec or not remaining:
        return remaining
    pos = spec.get(remaining[0])
    if pos is None:
        return remaining
    args = remaining[1:]
    if pos >= len(args):
        return remaining
    token = args[pos]
    if not isinstance(token, str) or not re.match(
        r"^[A-Za-z][A-Za-z0-9]*-\d+$", token.strip()
    ):
        return remaining
    try:
        from yoke_core.domain.yok_n_parser import parse_item_id
        normalized = str(parse_item_id(token))
    except ValueError:
        match = re.match(r"^[A-Za-z][A-Za-z0-9]*-0*(\d+)$", token.strip())
        if not match:
            return remaining
        normalized = str(int(match.group(1)))
    rewritten = list(args)
    rewritten[pos] = normalized
    return [remaining[0], *rewritten]


# Entry point — kept inline for dispatch monkey-patch tests.

def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry — dispatches ``<domain> <subcmd> …`` to the right owner."""
    if argv is None:
        argv = sys.argv[1:]

    if argv and argv[0] in {"-h", "--help"}:
        _print_usage(stream=sys.stdout)
        return 0
    if len(argv) >= 2 and argv[1] in {"-h", "--help", "help"}:
        _print_domain_help(argv[0])
        return 0

    repo_root = _repo_root()

    forced_init = bool(argv) and argv[0] == "init"
    _auto_init(repo_root, forced=forced_init)

    remediation_exit = _probe_schema_or_remediate(argv)
    if remediation_exit is not None:
        return remediation_exit

    if not argv:
        print("Error: no domain specified", file=sys.stderr)
        print("", file=sys.stderr)
        _print_usage()
        return 2

    domain = argv[0]
    remaining = argv[1:]

    if domain == "query":
        return _dispatch_python_module("yoke_core.cli.raw_query", remaining)

    if domain == "init":
        print("DB initialized")
        return 0

    if domain == "help":
        if remaining:
            _print_domain_help(remaining[0])
        else:
            _print_usage(stream=sys.stdout)
        return 0

    if domain == "items":
        if not remaining:
            print("Error: items requires a subcommand", file=sys.stderr)
            _print_domain_help("items")
            return 2
        subcmd = remaining[0]
        item_args = remaining[1:]
        if subcmd == "--list-subcommands":
            _print_domain_help("items")
            return 0
        if subcmd == "get" and "--section" in item_args:
            return _dispatch_items_get_section(item_args)
        if subcmd in _ITEMS_READ_SUBCMDS:
            return _dispatch_python_module(
                "yoke_core.domain.query_items_cli",
                [subcmd, *item_args],
            )
        if subcmd in _ITEMS_WRITE_SUBCMDS:
            return _dispatch_module_function(
                "yoke_core.api.service_client",
                "cmd_backlog_cli",
                [subcmd, *item_args],
            )
        emit_unknown_items_subcmd_hint(subcmd)
        return 2

    if domain == "merge":
        if not remaining or remaining[0] != "run":
            print("Error: merge requires 'run' subcommand", file=sys.stderr)
            _print_domain_help("merge")
            return 2
        return _dispatch_python_module(
            "yoke_core.engines.merge_worktree",
            remaining[1:],
        )

    py_module = _DOMAIN_PY_MODULES.get(domain)
    if py_module:
        remaining = _normalize_yok_n_arg(domain, remaining)
        if emit_unknown_domain_subcmd_hint(domain, py_module, remaining):
            return 2
        return _dispatch_python_module(py_module, remaining)

    emit_unknown_domain_hint(domain)
    return 2


if __name__ == "__main__":
    sys.exit(main())
