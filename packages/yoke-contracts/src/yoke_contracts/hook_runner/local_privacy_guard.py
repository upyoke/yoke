"""Pure command classification for operator-machine privacy boundaries.

Fleet workers may inspect their repository, worktree, scratch roots, and named
harness dot-directories. They must not discover tools by walking the operator's
home, touch macOS privacy-managed folders, or run local GUI automation. The
classifier is dependency-free so the full engine guard and the product-local
HTTPS fallback enforce one contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import re
import shlex
from pathlib import Path
from typing import Iterable, Sequence


LOCAL_PRIVACY_INTEGRATION_ENV = "YOKE_ALLOW_LOCAL_PRIVACY_INTEGRATION"

_SHELLS = frozenset({"bash", "dash", "ksh", "sh", "zsh"})
_LOCAL_AUTOMATION = {
    "osascript": "Apple Events",
    "screencapture": "Screen Recording",
}
_DIRECT_READERS = frozenset(
    "awk cat file head open readlink realpath sed stat tail test wc".split()
)
_PROTECTED_HOME_ROOTS = (
    ("Desktop",),
    ("Documents",),
    ("Downloads",),
    ("Movies",),
    ("Music",),
    ("Photos",),
    ("Pictures",),
    ("Library", "CloudStorage"),
    ("Library", "Mobile Documents"),
)
_SYSTEM_PRIVACY_DATABASE = Path("/Library/Application Support/com.apple.TCC/TCC.db")
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_GLOB_CHARS = frozenset("*?[")
_RG_VALUE_OPTIONS = frozenset(
    (
        "-A -B -C -E -e -f -g -j -M -m -r -t -T --after-context "
        "--before-context --context --encoding --engine --file --glob --iglob "
        "--max-columns --max-count --max-depth --regexp --replace --threads "
        "--type --type-not"
    ).split()
)
_GREP_VALUE_OPTIONS = frozenset(
    (
        "-A -B -C -e -f -m --after-context --before-context --context "
        "--file --max-count --regexp"
    ).split()
)


@dataclass(frozen=True)
class LocalPrivacyViolation:
    """One command shape that would cross the operator privacy boundary."""

    code: str
    target: str
    service: str

    def reason(self) -> str:
        recovery = (
            "Anchor searches in the repository/worktree or a named harness "
            "dot-directory. For native harness binary discovery, use "
            "resolve_native_cli/resolve_native_cli_source; _CLI_FALLBACKS "
            "owns bundled application paths. Run GUI automation and privacy "
            "probes only on the sanctioned target host, never the operator machine."
        )
        return (
            "BLOCKED: local privacy boundary would be crossed.\n\n"
            f"Reason: {self.code}\nTarget: {self.target}\n"
            f"Privacy scope: {self.service}\n\nRecovery: {recovery}"
        )


def _segments(command: str) -> list[list[str]]:
    """Return quote-aware command segments separated by shell operators."""
    try:
        lexer = shlex.shlex(
            command.replace("\n", " ; "),
            posix=True,
            punctuation_chars=";&|",
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return []
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token and set(token) <= set(";&|"):
            if current:
                segments.append(current)
            current = []
        else:
            current.append(token)
    if current:
        segments.append(current)
    return segments


def _unwrap(tokens: Sequence[str]) -> tuple[str, list[str]]:
    index = 0
    while index < len(tokens) and _ASSIGNMENT.match(tokens[index]):
        index += 1
    while index < len(tokens):
        executable = Path(tokens[index]).name
        if executable in {"command", "exec", "nohup", "sudo"}:
            index += 1
            while index < len(tokens) and tokens[index].startswith("-"):
                index += 1
            continue
        if executable == "env":
            index += 1
            while index < len(tokens) and (
                tokens[index].startswith("-") or _ASSIGNMENT.match(tokens[index])
            ):
                index += 1
            continue
        return executable, list(tokens[index + 1 :])
    return "", []


def _expanded_path(
    token: str,
    home: Path,
    cwd: str | os.PathLike[str] | None = None,
) -> str | None:
    value = token
    if value == "~" or value.startswith("~/"):
        value = str(home) + value[1:]
    elif value == "$HOME" or value.startswith("$HOME/"):
        value = str(home) + value[len("$HOME") :]
    elif value == "${HOME}" or value.startswith("${HOME}/"):
        value = str(home) + value[len("${HOME}") :]
    if not os.path.isabs(value):
        if cwd is None or value.startswith("-"):
            return None
        value = os.path.join(os.fspath(cwd), value)
    return os.path.normpath(value)


def _path_violation(
    token: str,
    home: Path,
    cwd: str | os.PathLike[str] | None = None,
) -> LocalPrivacyViolation | None:
    expanded = _expanded_path(token, home, cwd)
    if expanded is None:
        return None
    if expanded == str(_SYSTEM_PRIVACY_DATABASE) or expanded.startswith(
        str(_SYSTEM_PRIVACY_DATABASE.parent) + os.sep
    ):
        return LocalPrivacyViolation(
            "local_privacy_database", token, "Full Disk Access"
        )
    home_text = os.path.normpath(str(home))
    if expanded == home_text:
        return LocalPrivacyViolation("home_root_scan", token, "user home")
    if not expanded.startswith(home_text + os.sep):
        return None
    relative = expanded[len(home_text) + 1 :]
    parts = tuple(part for part in relative.split(os.sep) if part)
    for protected in _PROTECTED_HOME_ROOTS:
        if parts[: len(protected)] == protected:
            return LocalPrivacyViolation(
                "protected_home_access", token, "/".join(protected)
            )
    if parts and any(char in parts[0] for char in _GLOB_CHARS):
        return LocalPrivacyViolation("home_root_glob", token, "user home")
    return None


def _implicit_scan(
    cwd: str | os.PathLike[str] | None, home: Path
) -> LocalPrivacyViolation | None:
    if cwd is None:
        return None
    return _path_violation(os.fspath(cwd), home)


def _option_positionals(
    args: Sequence[str], value_options: frozenset[str]
) -> tuple[list[str], bool]:
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


def _first_path_violation(
    paths: Iterable[str],
    home: Path,
    cwd: str | os.PathLike[str] | None,
) -> LocalPrivacyViolation | None:
    for target in paths:
        violation = _path_violation(target, home, cwd)
        if violation is not None:
            return violation
    return None


def _scan_segment(
    tokens: Sequence[str], *, home: Path, cwd: str | os.PathLike[str] | None
) -> LocalPrivacyViolation | None:
    executable, args = _unwrap(tokens)
    if not executable:
        return None
    if executable in _LOCAL_AUTOMATION:
        return LocalPrivacyViolation(
            "local_gui_automation", executable, _LOCAL_AUTOMATION[executable]
        )
    if executable in _SHELLS:
        for index, token in enumerate(args[:-1]):
            if "c" in token.lstrip("-") and token.startswith("-"):
                return classify_shell_command(args[index + 1], home=home, cwd=cwd)
        return None

    if executable == "find":
        roots: list[str] = []
        for token in args:
            if token in {"-H", "-L", "-P"} and not roots:
                continue
            if token.startswith("-") or token in {"!", "(", ")"}:
                break
            roots.append(token)
        return _first_path_violation(roots, home, cwd) or (
            _implicit_scan(cwd, home) if not roots else None
        )
    if executable in {"ls", "du", "tree"}:
        return _first_path_violation(
            (token for token in args if not token.startswith("-")), home, cwd
        )
    if executable in {"fd", "fdfind"}:
        positionals = [token for token in args if not token.startswith("-")]
        paths = positionals[1:]
        return _first_path_violation(paths, home, cwd) or (
            _implicit_scan(cwd, home) if not paths else None
        )
    if executable in {"rg", "ripgrep"}:
        positionals, expression_supplied = _option_positionals(args, _RG_VALUE_OPTIONS)
        files_mode = "--files" in args
        paths = positionals if files_mode or expression_supplied else positionals[1:]
        return _first_path_violation(paths, home, cwd) or (
            _implicit_scan(cwd, home) if not paths else None
        )
    if executable in {"grep", "egrep", "fgrep"} and any(
        flag in args for flag in ("-r", "-R", "--recursive")
    ):
        positionals, expression_supplied = _option_positionals(
            args, _GREP_VALUE_OPTIONS
        )
        paths = positionals if expression_supplied else positionals[1:]
        return _first_path_violation(paths, home, cwd) or (
            _implicit_scan(cwd, home) if not paths else None
        )
    if executable in _DIRECT_READERS:
        return _first_path_violation(args, home, cwd)
    return None


def classify_shell_command(
    command: str,
    *,
    home: Path,
    cwd: str | os.PathLike[str] | None = None,
) -> LocalPrivacyViolation | None:
    """Return the first operator-machine privacy violation in ``command``."""
    for segment in _segments(command):
        violation = _scan_segment(segment, home=home, cwd=cwd)
        if violation is not None:
            return violation
    return None


def classify_subprocess_args(
    args: str | Sequence[object],
    *,
    home: Path,
    cwd: str | os.PathLike[str] | None = None,
) -> LocalPrivacyViolation | None:
    """Classify a :class:`subprocess.Popen` argv/string without executing it."""
    if isinstance(args, str):
        command = args
    else:
        parts = [
            os.fspath(value) if isinstance(value, os.PathLike) else value
            for value in args
        ]
        command = shlex.join(
            [
                os.fsdecode(value) if isinstance(value, bytes) else str(value)
                for value in parts
            ]
        )
    return classify_shell_command(command, home=home, cwd=cwd)


__all__ = [
    "LOCAL_PRIVACY_INTEGRATION_ENV",
    "LocalPrivacyViolation",
    "classify_shell_command",
    "classify_subprocess_args",
]
