"""Extract pytest argv from executable shell sources, never quoted data.

The shared shell parse owns statement boundaries, assignments, ``env``
prefixes and heredoc bodies. This consumer only unwraps supported launchers
and shell execution payloads; it does not interpret variables, Python, or
arbitrary programs. A heredoc body is input: only a shell reading it, or the
substitutions an unquoted body expands, runs.
"""

from __future__ import annotations

import re
import shlex
from collections.abc import Iterator

from yoke_contracts.hook_runner.shell_parse import (
    ASSIGNMENT,
    ShellParse,
    ShellSegment,
    parse_shell,
)
from yoke_core.domain.path_claim_bash_substitution import executable_substitutions

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


def _split_string(segment: ShellSegment) -> list[str]:
    """Words an ``env -S STRING`` prefix adds before the command word."""
    prefix = segment.tokens[: len(segment.tokens) - len(segment.argv)]
    for index, word in enumerate(prefix[:-1]):
        if word == "-S":
            return shlex.split(prefix[index + 1])
    return []


def executable_argv(segment: ShellSegment) -> list[str]:
    """Strip compound punctuation, ``if`` and supported launchers."""
    argv = [*_split_string(segment), *segment.argv]
    # A shell comment ends the command; its words are not operands.
    comment = next((i for i, word in enumerate(argv) if word.startswith("#")), None)
    argv = argv[:comment]
    if argv:
        # A grouping brace or paren glued to the first or last word.
        argv[0] = argv[0].lstrip("({")
        argv[-1] = argv[-1].rstrip(")}")
        argv = [word for word in argv if word]
    # The shared parse drops the reserved word ``time`` but keeps its options.
    argv = _options(argv, _VALUE_OPTIONS["time"])
    while argv:
        if argv[0] == "if" or ASSIGNMENT.match(argv[0]):
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


def _is_shell(argv: list[str]) -> bool:
    return bool(argv) and argv[0].rsplit("/", 1)[-1] in _SHELLS


def _piped_text(sender: list[str]) -> str | None:
    """Literal text ``echo``/``printf`` emits into a receiving shell."""
    program = sender[0].rsplit("/", 1)[-1] if sender else ""
    if program == "echo" and sender[1:] and not sender[1].startswith("-"):
        return " ".join(sender[1:])
    if program == "printf" and len(sender) >= 2:
        if sender[1] in ("%s", "%s\\n"):
            return "\n".join(sender[2:])
        if "%" not in sender[1]:
            return sender[1].replace("\\n", "\n")
        if "pytest" in " ".join(sender):
            return "'unresolved printf shell source with pytest"
    return None


def _segment_starts(parsed: ShellParse) -> list[int]:
    """Offset of each segment's text in ``parsed.code``."""
    starts: list[int] = []
    cursor = 0
    for segment in parsed.segments:
        found = parsed.code.find(segment.text, cursor)
        starts.append(found if found >= 0 else cursor)
        cursor = starts[-1] + len(segment.text)
    return starts


def shell_sources(parsed: ShellParse) -> list[str]:
    """Shell source a parsed command runs besides its own segments.

    Substitutions, a heredoc body a shell reads (directly or through a
    later pipeline stage), the substitutions an unquoted body expands, and
    literal text piped into a shell.
    """
    _, sources = executable_substitutions(parsed.code)
    argvs = [executable_argv(segment) for segment in parsed.segments]
    starts = _segment_starts(parsed)
    for heredoc in parsed.heredocs:
        owner = max(
            (i for i, start in enumerate(starts) if start <= heredoc.operator_offset),
            default=None,
        )
        fed_to_shell = owner is not None and any(
            _is_shell(argvs[i])
            for i, segment in enumerate(parsed.segments)
            if segment.pipeline == parsed.segments[owner].pipeline
            and segment.stage >= parsed.segments[owner].stage
        )
        if fed_to_shell:
            sources.append(heredoc.body)
        elif heredoc.expands:
            sources.extend(executable_substitutions(heredoc.body, literal_quotes=True)[1])
    last_stages = {segment.pipeline: i for i, segment in enumerate(parsed.segments)}
    for receiver in last_stages.values():
        sender = receiver - 1
        if sender < 0 or parsed.segments[sender].pipeline != parsed.segments[receiver].pipeline:
            continue
        if _is_shell(argvs[receiver]):
            text = _piped_text(argvs[sender])
            if text is not None:
                sources.append(text)
    return sources


def argv_shell_sources(argv: list[str]) -> list[str]:
    """Shell source an ``eval``, ``sh -c`` or ``sh <<<`` argv runs."""
    program = argv[0].rsplit("/", 1)[-1] if argv else ""
    if program == "eval":
        return [" ".join(argv[1:])]
    if program not in _SHELLS:
        return []
    sources = []
    if "<<<" in argv and argv.index("<<<") + 1 < len(argv):
        sources.append(argv[argv.index("<<<") + 1])
    for index, option in enumerate(argv[1:], 1):
        if option.startswith("-") and not option.startswith("--") and "c" in option[1:]:
            if index + 1 < len(argv):
                sources.append(argv[index + 1])
            break
    return sources


def raw_pytest_invocations(
    command: str | ShellParse, *, depth: int = 0
) -> Iterator[list[str]]:
    """Yield raw pytest argv; unresolved sources yield an advisory marker.

    Substitutions run even in a wrapper's arguments. Shell -c and eval
    operands become shell sources; ordinary quoted argv remains data.
    Unknown syntax with pytest evidence is advisory, never admission.
    """
    if depth > 20:
        yield ["unresolved shell nesting; use yoke watch pytest"]
        return
    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    for source in shell_sources(parsed):
        yield from raw_pytest_invocations(source, depth=depth + 1)
    if any("pytest" in statement for statement in parsed.unparsed):
        yield ["unresolved shell quoting; use yoke watch pytest"]
    for segment in parsed.segments:
        argv = executable_argv(segment)
        args = pytest_arguments(list(argv))
        if args is not None:
            yield args
            continue
        for source in argv_shell_sources(argv):
            yield from raw_pytest_invocations(source, depth=depth + 1)
