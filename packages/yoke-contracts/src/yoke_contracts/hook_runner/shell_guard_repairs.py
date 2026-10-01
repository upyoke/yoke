"""Small, shell-aware repairs shared by local and relayed hook guards."""

from __future__ import annotations

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


def glob_repair(command: str, token: str, cwd: str) -> tuple[str, list[str]] | None:
    """Return a quoted rg glob command and nearby files sharing its stem."""
    for segment in shell_segments(command):
        if (
            not segment
            or segment[0].rsplit("/", 1)[-1]
            not in {"rg", "grep", "egrep", "fgrep", "ls"}
            or token not in segment
        ):
            continue
        parent, name = str(Path(token).parent), Path(token).name
        stem = re.split(r"[*?\[]", name, maxsplit=1)[0]
        directory = Path(cwd) / parent
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
                        for path in tracked.stdout.decode("utf-8", "replace").split(
                            "\0"
                        )
                        if path and Path(path).name.startswith(stem)
                    )[:STEM_MATCH_LIMIT]
            except (OSError, subprocess.TimeoutExpired):
                pass
        base = segment[0].rsplit("/", 1)[-1]
        if base == "ls":
            arguments = ["--files"]
        elif base in {"grep", "egrep", "fgrep"}:
            arguments = [
                next(
                    (
                        arg
                        for arg in segment[1:]
                        if arg != token and not arg.startswith("-")
                    ),
                    "",
                )
            ]
            if not arguments[0]:
                return None
        else:
            arguments = [arg for arg in segment[1:] if arg != token]
        repaired = shlex.join(["rg", *arguments, parent, "--glob", name])
        return repaired, matches
    return None


__all__ = [
    "NOTHING_RAN",
    "RIPGREP_REPLACE_CHECK_ID",
    "executing_shell",
    "glob_repair",
    "is_compound",
    "ripgrep_replace_repair",
    "shell_segments",
]
