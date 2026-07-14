"""Help-text rendering for the db_router CLI.

Owns the top-level usage block printed by ``db_router help`` (and on
unknown-domain errors) plus the per-domain subcommand hints. The actual
subcommand grammar lives in each target domain module — these helpers
only describe how to reach them.
"""

from __future__ import annotations

import sys

from yoke_core.cli.db_router_dispatch import (
    _DOMAIN_PY_MODULES,
    _ITEMS_READ_SUBCMDS,
    _ITEMS_WRITE_SUBCMDS,
)


# Canonical domain table — single source of truth for `_print_usage` and the
# nearest-match suggestion path in `db_router_suggestions`.
DOMAIN_TABLE = [
    ("items",            "Backlog item reads and writes"),
    ("epic",             "Epic task management"),
    ("ouroboros",        "Learning loop entries and wrapups"),
    ("shepherd",         "Verdicts, caveats, and dependencies"),
    ("release",          "Release notes management"),
    ("projects",         "Project registry management"),
    ("project-structure","Project Structure aggregate (path registry constitution)"),
    ("flows",            "Deployment flow definitions"),
    ("events",           "Structured event logging"),
    ("runs",             "Deployment runs lifecycle"),
    ("envs",             "Ephemeral environment management"),
    ("qa",               "QA requirements, runs, and artifacts"),
    ("harness-sessions", "Active session tracking and work claims"),
    ("sections",         "Item sections CRUD (item_sections table)"),
    ("merge",            "Worktree merge operations"),
    ("query",            "Raw SQL escape hatch"),
    ("init",             "Initialize DB schema"),
    ("help",             "Show this help or domain-specific subcommands"),
]
ALL_DOMAINS = tuple(name for name, _ in DOMAIN_TABLE)


def _print_usage(stream=None) -> None:
    if stream is None:
        stream = sys.stderr
    print(
        "Usage: python3 -m yoke_core.cli.db_router <domain> <subcommand> [args...]",
        file=stream,
    )
    print("", file=stream)
    print("Domains:", file=stream)
    for name, desc in DOMAIN_TABLE:
        print(f"  {name:18} {desc}", file=stream)


def _print_domain_help(domain: str) -> None:
    """Print a short usage hint for a domain.

    For domains that route to a Python module, this invokes the module's
    ``main(["--help"])`` if the module supports it; otherwise it prints
    a generic pointer. For the items, merge, query, and init domains, it
    prints the router-specific help text.
    """
    if domain == "items":
        print("items subcommands:", file=sys.stderr)
        print("", file=sys.stderr)
        print("  Reads  (in-process via query_items_cli):", file=sys.stderr)
        for sub in sorted(_ITEMS_READ_SUBCMDS):
            print(f"    {sub}", file=sys.stderr)
        print("", file=sys.stderr)
        print("  Writes (via service_client backlog-cli):", file=sys.stderr)
        for sub in sorted(_ITEMS_WRITE_SUBCMDS):
            print(f"    {sub}", file=sys.stderr)
        return
    if domain == "merge":
        print("merge subcommands:", file=sys.stderr)
        print(
            "  run <branch> <target-branch> [worktree-plan.md]",
            file=sys.stderr,
        )
        print(
            "    Dispatch to yoke_core.engines.merge_worktree.",
            file=sys.stderr,
        )
        return
    if domain == "query":
        from yoke_core.cli import raw_query
        raw_query._print_help(sys.stdout)
        return
    if domain == "init":
        print(
            "init: run auto-init (schema + domain bootstrap). Idempotent.",
            file=sys.stderr,
        )
        return
    py_module = _DOMAIN_PY_MODULES.get(domain)
    if not py_module:
        print(f"Unknown domain: {domain}", file=sys.stderr)
        print("", file=sys.stderr)
        _print_usage()
        return
    print(f"{domain} → {py_module}", file=sys.stderr)
    print(
        f"  For full subcommand help, invoke: python3 -m {py_module} --help",
        file=sys.stderr,
    )
