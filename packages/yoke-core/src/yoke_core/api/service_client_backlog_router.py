"""Top-level CLI dispatcher for the public backlog item surface.

Owns ``backlog-cli`` and dispatches each subcommand to the appropriate
handler.  Each handler is imported directly from its canonical owner sibling
(no two-hop through the shim).
"""

from __future__ import annotations

import sys

from yoke_core.api.service_client_backlog_batch_update import (
    cmd_execute_batch_update_cli,
)
from yoke_core.api.service_client_backlog_close import cmd_execute_close
from yoke_core.api.service_client_backlog_create import cmd_execute_create_cli
from yoke_core.api.service_client_backlog_github import cmd_backlog_github
from yoke_core.api.service_client_backlog_query import (
    cmd_backlog_dedup_search,
    cmd_backlog_list_cli,
)
from yoke_core.api.service_client_backlog_scalar import (
    cmd_block,
    cmd_freeze,
    cmd_thaw,
    cmd_unblock,
)
from yoke_core.api.service_client_backlog_update import cmd_execute_update_cli
from yoke_core.api.service_client_items_validation import cmd_item_next_id


def cmd_backlog_cli(args: list[str]) -> int:
    """Own the public backlog-registry CLI routing shape in Python."""
    from yoke_core.domain import backlog

    def _usage(exit_code: int = 1) -> int:
        stream = sys.stdout if exit_code == 0 else sys.stderr
        print("Usage: python3 -m yoke_core.api.service_client backlog-cli <subcommand> [args]", file=stream)
        print("       python3 -m yoke_core.cli.db_router items <subcommand> [args]      # canonical router shape", file=stream)
        print("", file=stream)
        print("Worked example (write to a structured field — the canonical agent path):", file=stream)
        print("  printf '%s' \"$content\" | \\", file=stream)
        print("    python3 -m yoke_core.cli.db_router items update YOK-N spec --stdin", file=stream)
        print("", file=stream)
        print("  python3 -m yoke_core.cli.db_router items update YOK-N priority high", file=stream)
        print("  python3 -m yoke_core.cli.db_router items update YOK-N status=implementing priority=high", file=stream)
        print("", file=stream)
        print("Subcommands:", file=stream)
        print("  add <title> <type> [status] [priority]                 — Create new item", file=stream)
        print("  update <id-number> <field> <value> [--no-rebuild]      — Update a scalar field", file=stream)
        print("  update <id-number> f1=v1 [f2=v2 ...] [--no-rebuild]    — Multi-field update", file=stream)
        print(
            "  update <id-number> spec (--stdin | --body-file <path>)  — Replace structured field "
            "(spec/design_spec/technical_plan/worktree_plan/shepherd_log/shepherd_caveats/test_results/deploy_log)",
            file=stream,
        )
        print("  batch-update <field>=<value> <id1> <id2> ... [--no-rebuild] — Bulk update one field", file=stream)
        print("  list [--status X] [--type X] [--priority X]            — List items", file=stream)
        print("  get-next-id                                            — Get next YOK-N ID", file=stream)
        print("  sync-item <id-number>                                  — Create/update GitHub issue + labels", file=stream)
        print("  sync-labels <id-number>                                — Compare and update all GitHub labels", file=stream)
        print("  close <id-number> --reason REASON                      — Cancel item and close its GitHub issue", file=stream)
        print("  close-issue <id-number>                                — Close GitHub issue for done item", file=stream)
        print("  post-comment <id-number> <old> <new>                   — Post status change to GitHub", file=stream)
        print("  sync-body <id-number>                                  — Update GitHub issue body from local", file=stream)
        print("  backfill-oversized-bodies                              — Resync every oversized GitHub body via compact mirror", file=stream)
        print("  rebuild-board [args...]                               — Deprecated; routes to yoke board rebuild", file=stream)
        print("  dedup-search <keywords>                                — Search titles and bodies for duplicates", file=stream)
        print("  freeze <id-number>                                     — Freeze item (frozen=true via items.scalar.update)", file=stream)
        print("  thaw <id-number>                                       — Thaw item (frozen=false via items.scalar.update)", file=stream)
        print('  block <id-number> "<reason>"                           — Block item (blocked=true + reason)', file=stream)
        print("  unblock <id-number>                                    — Unblock item (clear blocked flag + reason)", file=stream)
        print("", file=stream)
        print("Notes:", file=stream)
        print("  - `YOK-N` accepts a `YOK-`-prefixed or bare-integer item id (canonical normalization).", file=stream)
        print("  - Structured-field replace routes through `items.structured_field.replace` (dispatcher contract).", file=stream)
        print("  - Body is a virtual rendered field; raw-body writes are unsupported.", file=stream)
        return exit_code

    if not args:
        return _usage()
    if args[0] in {"-h", "--help"}:
        return _usage(0)

    subcmd = args[0]
    rest = args[1:]

    if subcmd == "update" and rest and rest[0] in ("-h", "--help"):
        print(
            "Usage: db_router items update <id-number> <field> <value> [--no-rebuild]\n"
            "       db_router items update <id-number> f1=v1 [f2=v2 ...] [--no-rebuild]\n"
            "       db_router items update <id-number> <structured-field> "
            "(--stdin | --body-file <path>)\n"
            "\n"
            "Worked example — canonical agent shape:\n"
            "  yoke lifecycle transition YOK-N --to implementing\n"
            "  printf '%s' \"$content\" | yoke items structured-field \\\n"
            "    replace YOK-N --field spec --stdin\n"
            "\n"
            "Operator-debug fallback inside a Yoke checkout (scalar / "
            "multi-field updates without a `yoke` CLI adapter yet):\n"
            "  python3 -m yoke_core.cli.db_router items update YOK-N priority high\n"
            "  python3 -m yoke_core.cli.db_router items update YOK-N \\\n"
            "    status=implementing priority=high\n"
            "  printf '%s' \"$content\" | \\\n"
            "    python3 -m yoke_core.cli.db_router items update YOK-N spec --stdin\n"
            "\n"
            "Structured fields (whole-field replace via --stdin or --body-file):\n"
            "  spec, design_spec, technical_plan, worktree_plan,\n"
            "  shepherd_log, shepherd_caveats, test_results, deploy_log\n"
            "\n"
            "Notes:\n"
            "  - Routes through ``items.structured_field.replace`` / "
            "``items.scalar.update`` (dispatcher contract).\n"
            "  - Body is a virtual rendered field; raw-body writes are unsupported.\n"
            "  - YOK-N accepts a ``YOK-``-prefixed or bare-integer item id."
        )
        return 0

    if subcmd == "add":
        return cmd_execute_create_cli(rest)
    if subcmd == "update":
        return cmd_execute_update_cli(rest)
    if subcmd == "batch-update":
        return cmd_execute_batch_update_cli(rest)
    if subcmd == "list":
        return cmd_backlog_list_cli(rest)
    if subcmd == "get-next-id":
        return cmd_item_next_id(rest)
    if subcmd == "sync-item":
        return cmd_backlog_github([subcmd, *rest])
    if subcmd == "close":
        return cmd_execute_close(rest)
    if subcmd in {
        "sync-labels",
        "close-issue",
        "post-comment",
        "sync-body",
        "backfill-oversized-bodies",
    }:
        return cmd_backlog_github([subcmd, *rest])
    if subcmd == "ingest-body":
        print(
            "Error: ingest-body is no longer supported. items.body is renderer-owned.",
            file=sys.stderr,
        )
        print(
            "Use structured field writes instead: printf '%s' \"$content\" | "
            "python3 -m yoke_core.cli.db_router items update <id> spec --stdin",
            file=sys.stderr,
        )
        return 1
    if subcmd == "rebuild-board":
        print(
            "Warning: backlog-cli rebuild-board is deprecated; "
            "use `yoke board rebuild`.",
            file=sys.stderr,
        )
        from yoke_cli.main import main as yoke_main
        return yoke_main(["board", "rebuild", *rest])
    if subcmd == "dedup-search":
        return cmd_backlog_dedup_search(rest)
    # Surface `--help` cleanly for the boolean-flag subcommands
    # before the underlying handlers reject `--help` as an item-id.
    _SCALAR_HELP = {
        "freeze": "Usage: backlog-cli freeze <id-number>",
        "thaw":   "Usage: backlog-cli thaw <id-number>",
        "block":  'Usage: backlog-cli block <id-number> "<reason>"',
        "unblock": "Usage: backlog-cli unblock <id-number>",
    }
    if subcmd in _SCALAR_HELP and rest and rest[0] in {"-h", "--help"}:
        print(_SCALAR_HELP[subcmd])
        return 0
    if subcmd == "freeze":
        return cmd_freeze(rest)
    if subcmd == "thaw":
        return cmd_thaw(rest)
    if subcmd == "block":
        return cmd_block(rest)
    if subcmd == "unblock":
        return cmd_unblock(rest)
    return _usage()


__all__ = [
    "cmd_backlog_cli",
]
