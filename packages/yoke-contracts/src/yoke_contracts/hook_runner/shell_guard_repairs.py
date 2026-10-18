"""Small, shell-aware repairs shared by local and relayed hook guards."""

from __future__ import annotations

import glob
import os
import shlex
import re
import subprocess
from itertools import islice
from pathlib import Path


NOTHING_RAN = "Nothing in this invocation ran. Retry the repaired command."
RIPGREP_REPLACE_CHECK_ID = "lint-ripgrep-replace"
STEM_MATCH_LIMIT = 8
_HEREDOC = re.compile(r"<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")


def executing_shell(payload: dict) -> str:
    """Resolve an explicit command shell before the harness's inherited default.

    The hook wrapper's own shell does not identify the command's shell.
    Missing shell evidence stays unknown rather than assuming zsh.
    """
    for key in ("tool_input", "toolInput", "input"):
        source = payload.get(key)
        if isinstance(source, dict) and isinstance(source.get("shell"), str):
            return Path(source["shell"].strip()).name
    shell = payload.get("shell")
    return Path(
        shell.strip() if isinstance(shell, str) else os.environ.get("SHELL", "")
    ).name


def _without_heredoc_bodies(command: str) -> str:
    kept: list[str] = []
    delimiter = ""
    for line in command.splitlines():
        if delimiter:
            if line.strip() == delimiter:
                delimiter = ""
            continue
        kept.append(line)
        match = _HEREDOC.search(line)
        if match:
            delimiter = match.group(1)
    return ";".join(kept)


def shell_segments(command: str) -> list[list[str]]:
    """Split shell operators without treating quoted text as an operator."""
    try:
        lexer = shlex.shlex(
            _without_heredoc_bodies(command), posix=True, punctuation_chars=";&|"
        )
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return []
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token and all(char in ";&|" for char in token):
            segments.append([])
        else:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def is_compound(command: str) -> bool:
    return len(shell_segments(command)) > 1


def ripgrep_replace_repair(command: str) -> str | None:
    """Return a safe `rg -n` command when `-r` was used as a search flag."""
    for segment in shell_segments(command):
        if not segment or segment[0].rsplit("/", 1)[-1] != "rg":
            continue
        repaired = list(segment)
        found = False
        for index, token in enumerate(segment[1:], 1):
            if token == "--":
                break
            if (
                token.startswith("-")
                and not token.startswith("--")
                and "r" in token[1:]
            ):
                found = True
                flags = token[1:].replace("r", "")
                repaired[index] = "-" + flags if flags else ""
        if found:
            repaired = [token for token in repaired if token]
            if not any(
                token == "-n"
                or (
                    token.startswith("-")
                    and not token.startswith("--")
                    and "n" in token[1:]
                )
                for token in repaired[1:]
            ):
                repaired.insert(1, "-n")
            return shlex.join(repaired)
    return None


_CD_OPTIONS = frozenset({"-L", "-P", "-e", "-@"})
_REDIRECT_PREFIXES = ("2>>", ">>", "&>", "2>", "1>", ">", "<")


def expanded_glob_path(token: str, cwd: str) -> Path:
    """Expand the executing user's home before resolving relative operands."""
    path = Path(os.path.expanduser(token))
    return path if path.is_absolute() else Path(os.path.expanduser(cwd)) / path


def _plain_cd_destination(segment: list[str]) -> str | None:
    """Operand of a plain ``cd DIR``, ignoring ``-L``/``-P``/``-e``/``-@``."""
    if not segment or segment[0] != "cd":
        return None
    operands = [token for token in segment[1:] if token not in _CD_OPTIONS]
    if len(operands) != 1:
        return None
    return operands[0]


def _advance_glob_base(base: str | None, destination: str) -> str | None:
    """Directory after ``cd destination``, or None when that target is unreadable."""
    if "$" in destination or "`" in destination or destination == "-":
        return None
    expanded = os.path.expanduser(destination)
    if expanded.startswith("~"):
        return None
    if not os.path.isabs(expanded):
        if not base:
            return None
        expanded = os.path.join(base, expanded)
    try:
        return str(Path(expanded).resolve())
    except (OSError, ValueError):
        return None


def _split_command_pieces(command: str) -> list[str]:
    """Split on unquoted shell separators, including newlines as ``;``."""
    text = ";".join(command.splitlines())
    pieces: list[str] = []
    buf: list[str] = []
    in_single = in_double = escaped = False
    index = 0
    while index < len(text):
        char = text[index]
        if escaped:
            buf.append(char)
            escaped = False
            index += 1
            continue
        if char == "\\" and not in_single:
            buf.append(char)
            escaped = True
            index += 1
            continue
        if char == "'" and not in_double:
            buf.append(char)
            in_single = not in_single
            index += 1
            continue
        if char == '"' and not in_single:
            buf.append(char)
            in_double = not in_double
            index += 1
            continue
        if not in_single and not in_double and char in ";&|":
            piece = "".join(buf).strip()
            if piece:
                pieces.append(piece)
            buf = []
            while index < len(text) and text[index] in ";&|":
                index += 1
            continue
        buf.append(char)
        index += 1
    piece = "".join(buf).strip()
    if piece:
        pieces.append(piece)
    return pieces


def glob_segment_bases(command: str, cwd: str) -> list[tuple[str, str | None]]:
    """Pair each command piece with the directory its globs resolve against.

    A plain ``cd DIR`` moves the base for later pieces. ``$``, a backtick, or
    ``cd -`` makes that base unknown so later globs are not denied.
    """
    base: str | None = cwd or None
    located: list[tuple[str, str | None]] = []
    for piece in _split_command_pieces(command):
        located.append((piece, base))
        parsed = shell_segments(piece)
        destination = _plain_cd_destination(parsed[0] if len(parsed) == 1 else [])
        if destination is not None:
            base = _advance_glob_base(base, destination)
    return located


def path_glob_is_unmatched(token: str, cwd: str) -> bool:
    """Check home, absolute and cwd-relative globs on the executing machine.

    An unexpanded ``$`` or backtick, or an unknown base, is allowed. A denial
    requires a resolved directory and a fully literal pattern.
    """
    if not cwd or "$" in token or "`" in token:
        return False
    try:
        return not glob.glob(str(expanded_glob_path(token, cwd)))
    except (OSError, ValueError):
        return False


def _is_shell_redirection(token: str) -> bool:
    return token.startswith(_REDIRECT_PREFIXES)


def glob_repair(command: str, token: str, cwd: str) -> tuple[str, list[str]] | None:
    """Return a quoted rg glob command and nearby files sharing its stem.

    ``cwd`` is the directory the unmatched glob was checked against. Shell
    redirections stay unquoted so they are not turned into arguments.
    """
    for segment in shell_segments(command):
        if (
            not segment
            or segment[0].rsplit("/", 1)[-1]
            not in {"rg", "grep", "egrep", "fgrep", "ls"}
            or token not in segment
        ):
            continue
        return _repaired_glob_command(segment, token, cwd)
    return None


def _repaired_glob_command(
    segment: list[str], token: str, cwd: str
) -> tuple[str, list[str]] | None:
    expanded = expanded_glob_path(token, cwd)
    parent, name = str(expanded.parent), expanded.name
    if not token.startswith(("~", "/")):
        parent = str(Path(token).parent)
    stem = re.split(r"[*?\[]", name, maxsplit=1)[0]
    directory = expanded.parent
    local = (
        (path for path in directory.glob(stem + "*") if path.is_file())
        if directory.is_dir()
        else iter(())
    )
    found = list(islice(local, STEM_MATCH_LIMIT))
    matches = sorted(
        str(path.relative_to(cwd)) if path.is_relative_to(cwd) else str(path)
        for path in found
    )
    if not matches and stem:
        try:
            tracked = subprocess.run(
                ["git", "-C", cwd, "ls-files", "-z"],
                capture_output=True,
                timeout=0.25,
                check=False,
            )
            if tracked.returncode == 0:
                matches = sorted(
                    path
                    for path in tracked.stdout.decode("utf-8", "replace").split("\0")
                    if path and Path(path).name.startswith(stem)
                )[:STEM_MATCH_LIMIT]
        except (OSError, subprocess.TimeoutExpired):
            pass
    redirections = [arg for arg in segment[1:] if _is_shell_redirection(arg)]
    command_name = segment[0].rsplit("/", 1)[-1]
    if command_name == "ls":
        arguments = ["--files"]
    elif command_name in {"grep", "egrep", "fgrep"}:
        arguments = [
            next(
                (
                    arg
                    for arg in segment[1:]
                    if arg != token
                    and not arg.startswith("-")
                    and not _is_shell_redirection(arg)
                ),
                "",
            )
        ]
        if not arguments[0]:
            return None
    else:
        arguments = [
            arg
            for arg in segment[1:]
            if arg != token and not _is_shell_redirection(arg)
        ]
    repaired = shlex.join(["rg", *arguments, parent, "--glob", name])
    if redirections:
        repaired = f"{repaired} {' '.join(redirections)}"
    return repaired, matches


__all__ = [
    "NOTHING_RAN",
    "RIPGREP_REPLACE_CHECK_ID",
    "executing_shell",
    "expanded_glob_path",
    "glob_segment_bases",
    "path_glob_is_unmatched",
    "glob_repair",
    "is_compound",
    "ripgrep_replace_repair",
    "shell_segments",
]
