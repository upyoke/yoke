"""One shell-command parse shared by every shell hook guard.

The hook runner parses a command once, with the parser for the shell that
runs it (:func:`parse_for_shell`), and hands the result to each guard, so
every guard agrees on what the command runs. PowerShell commands go through
``powershell_parse``; Bash (Git Bash included) through :func:`parse_shell`:

- Heredoc bodies are input, not commands. They are lifted out first and kept
  on ``ShellParse.heredocs`` with whether the shell expands them.
- Statements split on unquoted ``;``, ``&&``, ``||``, ``&`` and newlines,
  and pipelines on ``|``, before tokenizing, so ``--target-root /lane; git
  ...`` never glues the ``;`` onto ``/lane``. An operator inside ``$(...)``,
  backticks, ``<(...)`` or ``>(...)`` belongs to that substitution, so
  ``pytest $(find tests -name x.py | head -1)`` is one segment. Each segment
  records its ``pipeline`` and ``stage`` position.
- Each segment's ``argv`` drops leading compound keywords (``do``, ``then``),
  ``NAME=value`` assignments (``_``-prefixed names included) and an ``env``
  prefix with its options (``env -i``, ``env -u NAME``).
- ``segment_cwds`` follows every plain ``cd DIR`` in order, so a ``cd`` after
  an earlier command moves later relative paths too. A ``$VAR`` hop resolves
  only through bindings the caller passes for that segment; any other
  unreadable hop (a backtick, ``cd -``) makes later directories unknown.
  PowerShell's ``Set-Location``/``sl``/``chdir``/``Push-Location`` and
  ``pushd`` count as ``cd``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from yoke_contracts.hook_runner.command_extract import expand_variables
from yoke_contracts.hook_runner.shell_expansion_scan import Heredoc, scan
from yoke_contracts.hook_runner.shell_statements import iter_pipeline_groups
from yoke_contracts.hook_runner.shell_word import shell_words

ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
ENV_OPTIONS_WITH_ARG = frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"})
CD_OPTIONS = frozenset({"-L", "-P", "-e", "-@", "--"})
# Commands that change directory, compared case-insensitively.
CD_COMMANDS = frozenset({"cd", "pushd", "set-location", "sl", "chdir", "push-location"})
# PowerShell's directory parameters; the operand follows the flag.
CD_PATH_PARAMETERS = frozenset({"-path", "-literalpath"})
BASH = "bash"

# Reserved words that open or punctuate a compound statement. None of them
# is the command being run, so they are dropped before the command word.
COMPOUND_STATEMENT_KEYWORDS = frozenset(
    {
        "!", "(", ")", "{", "}", "case", "coproc", "do", "done", "elif",
        "else", "esac", "fi", "then", "time", "until", "while",
    }
)
# ``for NAME in <words>`` carries loop values, not command operands.
WORD_LIST_KEYWORDS = frozenset({"for", "select"})


@dataclass(frozen=True)
class ShellSegment:
    """One simple command: its text, its words and what actually runs."""

    text: str
    tokens: tuple[str, ...]
    assignments: tuple[str, ...]
    argv: tuple[str, ...]
    pipeline: int = 0
    stage: int = 0
    shell: str = BASH

    @property
    def program(self) -> str:
        """Basename of the command word, or ``""`` when nothing runs.

        PowerShell names are lowercased without ``\\`` directories or
        ``.exe``, because Windows command lookup ignores both.
        """
        if not self.argv:
            return ""
        if self.shell == BASH:
            return self.argv[0].rsplit("/", 1)[-1]
        name = self.argv[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        return name[:-4] if name.endswith(".exe") else name

    def assignment(self, name: str) -> str | None:
        """Value of the last leading ``name=value`` assignment, if any."""
        found = None
        for word in self.assignments:
            key, _, value = word.partition("=")
            if key == name:
                found = value
        return found


@dataclass(frozen=True)
class ShellParse:
    """A command split into the segments its shell would run."""

    command: str
    code: str
    heredocs: tuple[Heredoc, ...]
    segments: tuple[ShellSegment, ...]
    unparsed: tuple[str, ...]
    shell: str = BASH

    @property
    def is_compound(self) -> bool:
        return len(self.segments) + len(self.unparsed) > 1

    def segment_cwds(
        self,
        cwd: str,
        *,
        home: str | None = None,
        bindings: Sequence[Mapping[str, str]] = (),
    ) -> list[str]:
        """Directory each segment runs in, ``""`` where it cannot be known.

        ``bindings[i]`` holds the variables set before segment ``i``.
        """
        base = cwd or ""
        out: list[str] = []
        for index, segment in enumerate(self.segments):
            out.append(base)
            destination = cd_destination(segment.argv)
            if destination is not None:
                bound = bindings[index] if index < len(bindings) else None
                base = advance_cwd(base, destination, home=home, bindings=bound)
        return out


def parse_for_shell(command: str, shell: str) -> ShellParse:
    """Parse ``command`` with the parser for ``shell`` (``bash``/``powershell``)."""
    if shell == BASH:
        return parse_shell(command)
    if shell == "powershell":
        from yoke_contracts.hook_runner.powershell_parse import parse_powershell

        return parse_powershell(command)
    raise ValueError(
        f"unknown shell kind {shell!r}; declare it in yoke_contracts.harness_shell_tools"
    )


def parse_payload_shell(payload: Mapping[str, object]) -> ShellParse:
    """Parse a hook payload's command with the shell the payload names."""
    from yoke_contracts.harness_shell_tools import payload_shell_kind
    from yoke_contracts.hook_runner.command_extract import extract_command

    return parse_for_shell(extract_command(payload), payload_shell_kind(payload))


def parse_shell(command: str) -> ShellParse:
    """Parse a Bash ``command`` once for every guard; never raises."""
    text = command or ""
    scanned = scan(text)
    segments: list[ShellSegment] = []
    unparsed: list[str] = []
    groups = iter_pipeline_groups(scanned.code, shell_comments=True, split_background=True)
    for pipeline, stages in enumerate(groups):
        for stage, statement in enumerate(stages):
            try:
                tokens = shell_words(statement.replace("\\\n", " "))
            except ValueError:
                unparsed.append(statement)
                continue
            if tokens:
                segments.append(_segment(statement, tokens, pipeline, stage))
    return ShellParse(text, scanned.code, scanned.heredocs, tuple(segments), tuple(unparsed))


def _segment(text: str, tokens: list[str], pipeline: int = 0, stage: int = 0) -> ShellSegment:
    index = 0
    while index < len(tokens) and tokens[index] in COMPOUND_STATEMENT_KEYWORDS:
        index += 1
    if index < len(tokens) and tokens[index] in WORD_LIST_KEYWORDS:
        return ShellSegment(text, tuple(tokens), (), (), pipeline, stage)
    assignments: list[str] = []
    while index < len(tokens):
        word = tokens[index]
        if ASSIGNMENT.match(word):
            assignments.append(word)
            index += 1
            continue
        if word.rsplit("/", 1)[-1] != "env":
            break
        index += 1
        while index < len(tokens) and tokens[index].startswith("-") and tokens[index] != "--":
            option = tokens[index]
            index += 1
            if option in ENV_OPTIONS_WITH_ARG and index < len(tokens):
                index += 1
        if index < len(tokens) and tokens[index] == "--":
            index += 1
    return ShellSegment(
        text, tuple(tokens), tuple(assignments), tuple(tokens[index:]), pipeline, stage
    )


def strip_env_prefix(tokens: list[str] | tuple[str, ...]) -> list[str]:
    """Drop leading assignments and an ``env`` prefix from a token list."""
    return list(_segment("", list(tokens)).argv) if tokens else []


def cd_destination(argv: tuple[str, ...] | list[str]) -> str | None:
    """Operand of a plain ``cd DIR`` (or ``Set-Location -Path DIR``).

    ``-L``/``-P``/``-e``/``-@``/``--`` and PowerShell's ``-Path`` and
    ``-LiteralPath`` flags are not operands.
    """
    if not argv or argv[0].lower() not in CD_COMMANDS:
        return None
    operands = [
        token
        for token in argv[1:]
        if token not in CD_OPTIONS and token.lower() not in CD_PATH_PARAMETERS
    ]
    return operands[0] if len(operands) == 1 else None


def expand_home(path: str, *, home: str | None = None) -> str:
    """Expand the current user's ``~`` against ``home`` (default: this machine).

    An empty ``home`` (the client sent none) leaves ``~`` unexpanded.
    """
    if home is None:
        return os.path.expanduser(path)
    if not home:
        return path
    if path == "~":
        return home
    if path.startswith("~/"):
        return str(Path(home, path[2:]))
    return path


def advance_cwd(
    base: str,
    destination: str,
    *,
    home: str | None = None,
    bindings: Mapping[str, str] | None = None,
) -> str:
    """Directory after ``cd destination`` from ``base``; ``""`` when unknown.

    ``$NAME`` resolves only through ``bindings``; an unbound one is unknown.
    """
    if bindings:
        expanded_destination = expand_variables(destination, bindings)
        if expanded_destination is None:
            return ""
        destination = expanded_destination
    if "$" in destination or "`" in destination or destination == "-":
        return ""
    expanded = expand_home(destination, home=home)
    if expanded.startswith("~"):
        return ""
    if not os.path.isabs(expanded):
        if not base:
            return ""
        expanded = os.path.join(base, expanded)
    try:
        return str(Path(expanded).resolve())
    except (OSError, ValueError):
        return ""


__all__ = [
    "ASSIGNMENT",
    "BASH",
    "CD_COMMANDS",
    "CD_OPTIONS",
    "COMPOUND_STATEMENT_KEYWORDS",
    "ENV_OPTIONS_WITH_ARG",
    "ShellParse",
    "ShellSegment",
    "WORD_LIST_KEYWORDS",
    "advance_cwd",
    "cd_destination",
    "expand_home",
    "parse_for_shell",
    "parse_payload_shell",
    "parse_shell",
    "strip_env_prefix",
]
