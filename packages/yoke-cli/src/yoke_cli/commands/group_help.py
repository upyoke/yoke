"""Namespace-prefix help for registered ``yoke`` command groups."""

from __future__ import annotations

from typing import List, Optional, Sequence

from yoke_cli.commands.adapters.usage import ADAPTER_USAGE
from yoke_cli.commands.help_labels import labeled_cli_form
from yoke_cli.commands.registry import SUBCOMMAND_REGISTRY
from yoke_cli.commands.tool_shaped import TOOL_SHAPED_USAGE
from yoke_contracts.field_note_text import FOOTER as FIELD_NOTE_FOOTER


def emit_group_help_if_available(argv: Sequence[str]) -> Optional[int]:
    if len(argv) < 2 or argv[-1] not in ("-h", "--help", "help"):
        return None
    prefix = tuple(argv[:-1])
    if not prefix:
        return None

    rows: List[tuple[str, str, str]] = []
    for cli_tokens, (function_id, _adapter) in sorted(SUBCOMMAND_REGISTRY.items()):
        if len(cli_tokens) <= len(prefix) or cli_tokens[:len(prefix)] != prefix:
            continue
        cli_form = "yoke " + " ".join(cli_tokens)
        rows.append((cli_form, function_id, ADAPTER_USAGE.get(function_id, "")))

    tool_rows: List[tuple[str, str]] = []
    for cli_form, usage in sorted(TOOL_SHAPED_USAGE.items()):
        tokens = tuple(cli_form.split()[1:])
        if len(tokens) <= len(prefix) or tokens[:len(prefix)] != prefix:
            continue
        tool_rows.append((cli_form, usage))

    if not rows and not tool_rows:
        return None

    group = " ".join(prefix)
    print(f"yoke {group} - subcommand group.")
    print()
    print("Usage:")
    print(f"  yoke {group} <subcommand> [args...]")
    print()
    print("Available subcommands:")
    for cli_form, function_id, usage in rows:
        print(f"  {labeled_cli_form(cli_form)}")
        print(f"    -> {function_id}")
        if usage:
            print(f"    {usage}")
    for cli_form, usage in tool_rows:
        print(f"  {labeled_cli_form(cli_form)}")
        print("    -> client-local helper (no function id)")
        if usage:
            print(f"    {usage}")
    print()
    print(FIELD_NOTE_FOOTER)
    return 0
