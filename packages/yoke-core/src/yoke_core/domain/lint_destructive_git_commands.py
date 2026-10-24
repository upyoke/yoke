"""Command parsing for the destructive-git hook.

Shape classification and threatened-state rules live in
``yoke_contracts.hook_runner.destructive_git_rules``, shared with the
client-local guard.
"""

from __future__ import annotations

from typing import Tuple

from yoke_contracts.hook_runner.shell_parse import ShellParse, parse_shell


def parse_git_invocations(command: str | ShellParse) -> list[Tuple[list[str], str]]:
    """Return ``(git-args, -C path)`` for each git invocation in *command*.

    The shared parse drops compound-statement keywords (``do``, ``then``,
    …), assignments and an ``env`` prefix, which are not the command being
    run. The shape is the verb; argument spelling does not decide whether
    this is git.
    """
    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    out: list[Tuple[list[str], str]] = []
    for segment in parsed.segments:
        if segment.program != "git":
            continue
        tokens = segment.argv
        index = 1
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
            out.append((list(tokens[index:]), repo_path))
    return out
