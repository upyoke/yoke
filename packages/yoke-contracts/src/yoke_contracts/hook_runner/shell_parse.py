"""One shell-command parse shared by every Bash hook guard.

The hook runner parses a Bash command once and hands the result to each
guard, so every guard agrees on what the command runs:

- Heredoc bodies are input, not commands. They are lifted out first and kept
  on ``ShellParse.heredocs`` with whether the shell expands them.
- Statements split on unquoted ``;``, ``&&``, ``||``, ``&`` and newlines,
  and pipelines on ``|``, before tokenizing, so ``--target-root /lane; git
  ...`` never glues the ``;`` onto ``/lane``. Each segment records its
  ``pipeline`` and ``stage`` position.
- Each segment's ``argv`` drops leading compound keywords (``do``, ``then``),
  ``NAME=value`` assignments (``_``-prefixed names included) and an ``env``
  prefix with its options (``env -i``, ``env -u NAME``).
- ``segment_cwds`` follows every plain ``cd DIR`` in order, so a ``cd`` after
  an earlier command moves later relative paths too. An unreadable hop
  (``$VAR``, a backtick, ``cd -``) makes later directories unknown.
"""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

from yoke_contracts.hook_runner.shell_expansion_scan import Heredoc, scan
from yoke_contracts.hook_runner.shell_statements import iter_pipeline_groups

ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
ENV_OPTIONS_WITH_ARG = frozenset({"-u", "--unset", "-C", "--chdir", "-S", "--split-string"})
CD_OPTIONS = frozenset({"-L", "-P", "-e", "-@", "--"})

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

    @property
    def program(self) -> str:
        """Basename of the command word, or ``""`` when nothing runs."""
        return self.argv[0].rsplit("/", 1)[-1] if self.argv else ""

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
    """A Bash command split into the segments the shell would run."""

    command: str
    code: str
    heredocs: tuple[Heredoc, ...]
    segments: tuple[ShellSegment, ...]
    unparsed: tuple[str, ...]

    @property
    def is_compound(self) -> bool:
        return len(self.segments) + len(self.unparsed) > 1

    def segment_cwds(self, cwd: str, *, home: str | None = None) -> list[str]:
        """Directory each segment runs in, ``""`` where it cannot be known."""
        base = cwd or ""
        out: list[str] = []
        for segment in self.segments:
            out.append(base)
            destination = cd_destination(segment.argv)
            if destination is not None:
                base = advance_cwd(base, destination, home=home)
        return out


def parse_shell(command: str) -> ShellParse:
    """Parse ``command`` once for every guard; never raises."""
    text = command or ""
    scanned = scan(text)
    segments: list[ShellSegment] = []
    unparsed: list[str] = []
    groups = iter_pipeline_groups(scanned.code, shell_comments=True, split_background=True)
    for pipeline, stages in enumerate(groups):
        for stage, statement in enumerate(stages):
            try:
                tokens = shlex.split(statement.replace("\\\n", " "))
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
    """Operand of a plain ``cd DIR``, ignoring ``-L``/``-P``/``-e``/``-@``/``--``."""
    if not argv or argv[0] != "cd":
        return None
    operands = [token for token in argv[1:] if token not in CD_OPTIONS]
    return operands[0] if len(operands) == 1 else None


def expand_home(path: str, *, home: str | None = None) -> str:
    """Expand the current user's ``~`` against ``home`` (default: this machine)."""
    if home is None:
        return os.path.expanduser(path)
    if path == "~":
        return home
    if path.startswith("~/"):
        return str(Path(home, path[2:]))
    return path


def advance_cwd(base: str, destination: str, *, home: str | None = None) -> str:
    """Directory after ``cd destination`` from ``base``; ``""`` when unknown."""
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
    "CD_OPTIONS",
    "COMPOUND_STATEMENT_KEYWORDS",
    "ENV_OPTIONS_WITH_ARG",
    "ShellParse",
    "ShellSegment",
    "WORD_LIST_KEYWORDS",
    "advance_cwd",
    "cd_destination",
    "expand_home",
    "parse_shell",
    "strip_env_prefix",
]
