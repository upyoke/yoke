"""Command parsing for the destructive-git hook.

Shape classification and threatened-state rules live in
``yoke_contracts.hook_runner.destructive_git_rules``, shared with the
client-local guard.
"""

from __future__ import annotations

import re
from typing import Tuple

from yoke_core.domain.lint_shell_target_tokens import (
    command_operand_tokens,
    shell_command_segments,
)

_ENV_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def parse_git_invocations(command: str) -> list[Tuple[list[str], str]]:
    """Return ``(git-args, -C path)`` for each git invocation in *command*.

    Compound-statement keywords (``do``, ``then``, …) are not the command
    being run, so they are dropped before looking for ``git``. The shape
    is the verb; argument spelling does not decide whether this is git.
    """
    out: list[Tuple[list[str], str]] = []
    for tokens in shell_command_segments(command or ""):
        tokens = command_operand_tokens(tokens)
        index = 0
        while index < len(tokens) and _ENV_RE.match(tokens[index]):
            index += 1
        if index >= len(tokens) or tokens[index].rsplit("/", 1)[-1] != "git":
            continue
        index += 1
        repo_path = ""
        while index < len(tokens):
            token = tokens[index]
            if token == "-C" and index + 1 < len(tokens):
                repo_path = tokens[index + 1]
                index += 2
            elif token.startswith("-C") and len(token) > 2:
                repo_path = token[2:]
                index += 1
            elif token == "-c" and index + 1 < len(tokens):
                index += 2
            elif token.startswith("-"):
                index += 1
            else:
                break
        if index < len(tokens):
            out.append((tokens[index:], repo_path))
    return out
