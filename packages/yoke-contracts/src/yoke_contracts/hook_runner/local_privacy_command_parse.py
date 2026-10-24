"""Shell argv parsing for the local privacy classifier.

Kept separate from the classifier so that "what does this command line say"
and "what does that mean for the operator's machine" stay two questions.
Nothing here knows about privacy, and the classifier does not re-derive token
shapes.
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from yoke_contracts.hook_runner.shell_parse import strip_env_prefix

RG_VALUE_OPTIONS = frozenset(
    (
        "-A -B -C -E -e -f -g -j -M -m -r -t -T --after-context "
        "--before-context --context --encoding --engine --file --glob --iglob "
        "--max-columns --max-count --max-depth --regexp --replace --threads "
        "--type --type-not"
    ).split()
)
GREP_VALUE_OPTIONS = frozenset(
    (
        "-A -B -C -e -f -m --after-context --before-context --context "
        "--file --max-count --regexp"
    ).split()
)


def unwrap(argv: Sequence[str]) -> tuple[str, list[str]]:
    """Return the real executable and its arguments, past sudo/exec wrappers.

    ``argv`` already has its leading assignments and ``env`` prefix removed
    by the shared parse; a wrapper may carry another one.
    """
    tokens = list(argv)
    while tokens:
        executable = Path(tokens[0]).name
        if executable in {"command", "exec", "nohup", "sudo"}:
            index = 1
            while index < len(tokens) and tokens[index].startswith("-"):
                index += 1
            tokens = strip_env_prefix(tokens[index:])
            continue
        return executable, tokens[1:]
    return "", []


def option_positionals(
    args: Sequence[str], value_options: frozenset[str]
) -> tuple[list[str], bool]:
    """Split ``args`` into positionals, and say whether ``-e``/``--regexp`` ran.

    The flag matters because it moves the first positional from "the pattern"
    to "a path": ``rg -e foo bar`` searches ``bar`` while ``rg foo bar``
    searches ``bar`` too but ``rg foo`` searches the working directory.
    """
    positionals: list[str] = []
    expression_supplied = False
    consume_value = False
    after_options = False
    for token in args:
        if consume_value:
            consume_value = False
            continue
        if after_options:
            positionals.append(token)
            continue
        if token == "--":
            after_options = True
            continue
        option = token.split("=", 1)[0]
        if option in {"-e", "--regexp"}:
            expression_supplied = True
        if option in value_options:
            consume_value = "=" not in token
            continue
        if token.startswith("-"):
            continue
        positionals.append(token)
    return positionals, expression_supplied


__all__ = [
    "GREP_VALUE_OPTIONS",
    "RG_VALUE_OPTIONS",
    "option_positionals",
    "unwrap",
]
