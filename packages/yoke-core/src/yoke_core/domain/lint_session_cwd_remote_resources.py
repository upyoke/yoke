"""Remote resource operands are not local filesystem targets.

For golden capture, only ``--destination`` belongs to the Test Machine.
Probe files, shell redirects, and other operands keep local claim validation.
"""

from __future__ import annotations

from typing import Sequence

from yoke_core.domain.lint_session_cwd_host_command import (
    aws_log_group_indexes,
    remote_argv_indexes,
    yoke_subcommand_positionals,
)


def remote_resource_indexes(command_base: str, tokens: Sequence[str]) -> set[int]:
    """Combine known remote operands; shell redirects are validated first."""
    return (
        golden_capture_destination_indexes(command_base, tokens)
        | remote_argv_indexes(command_base, tokens)
        | aws_log_group_indexes(command_base, tokens)
    )


def golden_capture_destination_indexes(
    command_base: str,
    tokens: Sequence[str],
) -> set[int]:
    """Identify the remote destination in the exact golden-capture command."""
    if command_base != "yoke" or yoke_subcommand_positionals(tokens, limit=2) != [
        "test-machine",
        "golden-capture",
    ]:
        return set()
    indexes: set[int] = set()
    for index, token in enumerate(tokens):
        if token == "--":
            break
        if token == "--destination" and index + 1 < len(tokens):
            value = tokens[index + 1]
            if value and not value.startswith("-"):
                indexes.add(index + 1)
        elif token.startswith("--destination="):
            indexes.add(index)
    return indexes
