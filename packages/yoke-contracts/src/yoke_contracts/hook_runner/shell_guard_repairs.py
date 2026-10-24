"""Small, shell-aware repairs shared by local and relayed hook guards."""

from __future__ import annotations

import glob
import os
import re
import shlex
import subprocess
from itertools import islice
from pathlib import Path

from yoke_contracts.hook_runner.shell_parse import ShellParse, parse_shell


NOTHING_RAN = "Nothing in this invocation ran. Retry the repaired command."
RIPGREP_REPLACE_CHECK_ID = "lint-ripgrep-replace"
STEM_MATCH_LIMIT = 8
_ARRAY_ASSIGNMENT_OPEN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\+?=\(")
_GLOB_CHARS = frozenset("*?[")
_REDIRECT_PREFIXES = ("2>>", ">>", "&>", "2>", "1>", ">", "<")


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


def ripgrep_replace_repair(command: str | ShellParse) -> str | None:
    """Return `rg -n` when `-r` was used as a search flag; `-r '$1'` replaces."""
    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    for segment in parsed.segments:
        if segment.program != "rg":
            continue
        argv = segment.argv
        repaired = list(argv)
        found = False
        for index, token in enumerate(argv[1:], 1):
            if token == "--":
                break
            if token.startswith("-") and not token.startswith("--") and "r" in token[1:]:
                value = token[1:].split("r", 1)[1] or "".join(argv[index + 1:index + 2])
                if "$" in value:
                    continue
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
            prefix = segment.tokens[:len(segment.tokens) - len(argv)]
            return shlex.join([*prefix, *repaired])
    return None


def expanded_glob_path(token: str, cwd: str) -> Path:
    """Expand the executing user's home before resolving relative operands."""
    path = Path(os.path.expanduser(token))
    return path if path.is_absolute() else Path(os.path.expanduser(cwd)) / path


def _brace_alternatives(token: str):
    """Expand comma alternatives, including nested groups, without a shell."""
    pending = [token]
    while pending:
        pattern = pending.pop()
        group = re.search(r"\{([^{}]*,[^{}]*)\}", pattern)
        if group is None:
            yield pattern
        else:
            pending.extend(pattern[:group.start()] + choice + pattern[group.end():]
                           for choice in group[1].split(","))


def array_assignment_element(token: str) -> str:
    """Drop a zsh array assignment's ``NAME=(`` or ``)`` from one element."""
    token = _ARRAY_ASSIGNMENT_OPEN.sub("", token, count=1)
    return token[:-1] if token.endswith(")") and "(" not in token else token


def path_glob_is_unmatched(token: str, cwd: str) -> bool:
    """Check home, absolute and cwd-relative globs on the executing machine.

    An unexpanded ``$`` or backtick, or an unknown base, is allowed. A denial
    requires a resolved directory and literal brace-expanded alternatives.
    """
    if not cwd or "$" in token or "`" in token:
        return False
    try:
        return any(not glob.glob(str(expanded_glob_path(pattern, cwd)))
                   for pattern in _brace_alternatives(token))
    except (OSError, ValueError):
        return False


def _unquoted_words(text: str) -> list[str]:
    """Words of ``text`` built only from its unquoted characters.

    zsh never glob-expands quoted characters, and the shared parse's words
    no longer show which characters were quoted, so this reads the raw text.
    """
    words: list[str] = []
    current: list[str] = []
    in_single = in_double = escaped = False
    for char in text.replace("\\\n", " "):
        if escaped:
            if not in_single and not in_double:
                current.append(char)
            escaped = False
            continue
        if char == "\\" and not in_single:
            escaped = True
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if in_single or in_double:
            continue
        if char.isspace() or char in ";|&":
            if current:
                words.append("".join(current))
                current = []
            continue
        current.append(char)
    if current:
        words.append("".join(current))
    return words


def find_unmatched_path_glob(
    command: str | ShellParse, cwd: str
) -> tuple[str, str] | None:
    """Return the first unquoted path glob that matches nothing, with its base.

    Each segment's globs resolve against the directory its earlier ``cd``
    steps lead to; heredoc bodies are input and never scanned.
    """
    if not cwd:
        return None
    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    for segment, base in zip(parsed.segments, parsed.segment_cwds(cwd)):
        for word in _unquoted_words(segment.text):
            path = word
            for prefix in _REDIRECT_PREFIXES:
                if path.startswith(prefix):
                    path = path[len(prefix):]
                    break
            path = array_assignment_element(path)
            if "/" not in path or not _GLOB_CHARS & set(path):
                continue
            if path_glob_is_unmatched(path, base):
                return path, base
    return None


def glob_repair(
    command: str | ShellParse, token: str, cwd: str
) -> tuple[str, list[str]] | None:
    """Repair a simple search/list command, or keep the safe manual recipe.

    Parsed words retain brace groups and nested patterns. Shell programs and
    redirections cannot be faithfully rebuilt by joining their argument words.
    """
    parsed = command if isinstance(command, ShellParse) else parse_shell(command)
    if any(char in parsed.command for char in "<>$`();&|#\\\n"):
        return None
    if len(parsed.segments) != 1 or parsed.unparsed:
        return None
    segment = list(parsed.segments[0].tokens)
    name = segment[0].rsplit("/", 1)[-1]
    if name not in {"rg", "ls"} or segment.count(token) != 1 or segment[-1] != token:
        return None
    arguments = segment[1:-1]
    if name == "ls":
        if arguments:
            return None
        arguments = ["--files"]
    elif arguments != ["--files"]:
        flags = {"-n", "-l", "-i", "-F", "-S", "-s", "-w", "-x", "-c", "-q"}
        if not arguments or any(arg not in flags for arg in arguments[:-1]):
            return None
        if arguments[-1].startswith("-") or arguments[-1] == token:
            return None
    return _repaired_glob_command(arguments, token, cwd)


def _repaired_glob_command(
    arguments: list[str], token: str, cwd: str
) -> tuple[str, list[str]] | None:
    # Split before the first pattern component, never at a slash inside braces.
    first = re.search(r"[*?\[{]", token)
    if first is None:
        return None
    prefix, _, _ = token[:first.start()].rpartition("/")
    parent = prefix or ("/" if token.startswith("/") else ".")
    name = token[len(prefix) + 1:] if "/" in token[:first.start()] else token
    # Restrict emitted globs to syntax whose shell and rg meanings agree.
    if any(char in name for char in "[]") or "***" in name:
        return None
    remaining = name
    while "{" in remaining:
        group = re.search(r"\{([^{}]*)\}", remaining)
        if group is None or "," not in group[1] or "" in group[1].split(","):
            return None
        remaining = remaining[:group.start()] + "*" + remaining[group.end():]
    if "}" in remaining:
        return None
    expanded = expanded_glob_path(parent, cwd)
    if not expanded.is_dir():
        return None
    if token.startswith(("~", "/")):
        parent = str(expanded)

    stem = re.split(r"[*?\[]", name, maxsplit=1)[0]
    directory = expanded
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
    # rg anchors slash-containing globs at its cwd, not its search operand.
    relative = os.path.relpath(expanded, cwd)
    outside = relative == ".." or relative.startswith("../")
    pattern = "/" + (name if outside or relative == "." else relative + "/" + name)
    repaired = shlex.join(["rg", *arguments, "." if outside else parent, "--glob", pattern])
    if outside:
        repaired = shlex.join(["cd", str(expanded)]) + " && " + repaired
    return repaired, matches


__all__ = [
    "NOTHING_RAN",
    "RIPGREP_REPLACE_CHECK_ID",
    "array_assignment_element",
    "executing_shell",
    "expanded_glob_path",
    "find_unmatched_path_glob",
    "glob_repair",
    "path_glob_is_unmatched",
    "ripgrep_replace_repair",
]
