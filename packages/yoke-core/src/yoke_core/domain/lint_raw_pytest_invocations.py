"""Extract pytest argv from executable shell sources, never quoted data.

Shared helpers own quote-aware boundaries and compound prefixes. This
consumer only unwraps supported launchers and shell execution payloads;
it does not interpret variables, Python, or arbitrary programs.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterator

from yoke_core.domain.lint_shell_target_tokens import command_operand_tokens
from yoke_core.domain.path_claim_bash_splitter import (
    iter_pipeline_groups,
    split_pipeline,
)
from yoke_core.domain.path_claim_bash_substitution import executable_substitutions
from yoke_core.domain.lint_raw_pytest_full_suite_shell import strip_heredoc_bodies

_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_PYTHON = re.compile(r"python(?:\d+(?:\.\d+)*)?$")
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
_RUN_LAUNCHERS = frozenset({"uv", "poetry", "pdm", "rye"})
_VALUE_OPTIONS = {
    "uv": {"--project", "--directory", "--python", "--with", "--package"},
    "env": {"-u", "--unset", "-C", "--chdir"},
    "nice": {"-n", "--adjustment"},
    "time": {"-f", "--format", "-o", "--output"},
    "exec": {"-a"},
    "hatch": {"-e", "--env"},
}


def _options(argv: list[str], values: set[str]) -> list[str]:
    while argv and argv[0].startswith("-"):
        option = argv.pop(0)
        if option == "--":
            break
        if option in values and argv:
            argv.pop(0)
    return argv


def executable_argv(argv: list[str]) -> list[str]:
    """Strip assignments, compound punctuation and supported launchers."""
    # time is both shell punctuation and a launcher with value-taking flags.
    # Let the shared prefix classifier peel each preceding reserved word,
    # preserving time for the same option handling as /usr/bin/time.
    while argv and argv[0] != "time" and not command_operand_tokens(argv[:1]):
        if len(argv) > 1 and argv[0] in {"for", "select"}:
            return []
        argv = argv[1:]
    while argv:
        if argv[0] == "if" or _ASSIGNMENT.match(argv[0]):
            argv = argv[1:]
            continue
        program = argv[0].rsplit("/", 1)[-1]
        if program == "env" and "-S" in argv:
            index = argv.index("-S")
            if index + 1 < len(argv):
                argv = argv[:index] + shlex.split(argv[index + 1]) + argv[index + 2 :]
                continue
        if program == "yoke" and argv[1:4] == ["dev", "run", "--"]:
            argv = argv[4:]
        elif program in _RUN_LAUNCHERS | {"hatch"}:
            tail = _options(argv[1:], _VALUE_OPTIONS.get(program, set()))
            if not tail or tail[0] != "run":
                break
            argv = _options(tail[1:], _VALUE_OPTIONS.get(program, set()))
        elif program in {"env", "nice", "time", "command", "exec"}:
            argv = _options(argv[1:], _VALUE_OPTIONS.get(program, set()))
        else:
            break
        if argv and argv[0] != "time":
            argv = command_operand_tokens(argv)
    return argv


def pytest_arguments(argv: list[str]) -> list[str] | None:
    """Recognize Python's actual module option, not script argv."""
    if not argv:
        return None
    program = argv[0].rsplit("/", 1)[-1]
    if program == "pytest":
        return argv[1:]
    if not _PYTHON.fullmatch(program):
        return None
    tail = argv[1:]
    while tail:
        option = tail.pop(0)
        if option == "-m":
            return tail[1:] if tail and tail[0] == "pytest" else None
        if option.startswith("-m"):
            return tail if option == "-mpytest" else None
        if option in {"-c", "--", "-"} or not option.startswith("-"):
            return None
        if option in {"-W", "-X"} and tail:
            tail.pop(0)
    return None


def _piped_shell_sources(command: str) -> Iterator[str]:
    """Inspect literal text emitted into a shell, without executing a pipe."""
    for group in iter_pipeline_groups(
        command, shell_comments=True, split_background=True
    ):
        if len(group) < 2:
            continue
        try:
            receiver = executable_argv(shlex.split(group[-1], comments=True))
            sender = executable_argv(shlex.split(group[-2], comments=True))
        except ValueError:
            continue  # The ordinary invocation walk records unresolved quoting.
        if not receiver or receiver[0].rsplit("/", 1)[-1] not in _SHELLS or not sender:
            continue
        program = sender[0].rsplit("/", 1)[-1]
        if program == "echo" and sender[1:] and not sender[1].startswith("-"):
            yield " ".join(sender[1:])
        elif program == "printf" and len(sender) >= 2:
            if sender[1] in ("%s", "%s\\n"):
                yield "\n".join(sender[2:])
            elif "%" not in sender[1]:
                yield sender[1].replace("\\n", "\n")
            elif "pytest" in " ".join(sender):
                yield "'unresolved printf shell source with pytest"


def raw_pytest_invocations(command: str, *, depth: int = 0) -> Iterator[list[str]]:
    """Yield raw pytest argv; unresolved sources yield an advisory marker.

    Substitutions run even in a wrapper's arguments. Shell -c and eval
    operands become shell sources; ordinary quoted argv remains data.
    Unknown syntax with pytest evidence is advisory, never admission.
    """
    if depth > 20:
        yield ["unresolved shell nesting; use yoke watch pytest"]
        return
    command = strip_heredoc_bodies(command)
    outer, bodies = executable_substitutions(command)
    for body in [*bodies, *_piped_shell_sources(outer)]:
        yield from raw_pytest_invocations(body, depth=depth + 1)
    for segment in split_pipeline(outer, split_background=True, shell_comments=True):
        try:
            argv = executable_argv(
                shlex.split(segment.strip().lstrip("({").rstrip(")}"), comments=True)
            )
        except ValueError:
            if "pytest" in segment:
                yield ["unresolved shell quoting; use yoke watch pytest"]
            continue
        args = pytest_arguments(list(argv))
        if args is not None:
            yield args
            continue
        if not argv:
            continue
        program = argv[0].rsplit("/", 1)[-1]
        if program == "eval":
            yield from raw_pytest_invocations(" ".join(argv[1:]), depth=depth + 1)
        elif program in _SHELLS:
            if "<<<" in argv:
                index = argv.index("<<<")
                if index + 1 < len(argv):
                    yield from raw_pytest_invocations(argv[index + 1], depth=depth + 1)
            for index, option in enumerate(argv[1:], 1):
                if (
                    option.startswith("-")
                    and "c" in option[1:]
                    and not option.startswith("--")
                ):
                    if index + 1 < len(argv):
                        yield from raw_pytest_invocations(
                            argv[index + 1], depth=depth + 1
                        )
                    break
