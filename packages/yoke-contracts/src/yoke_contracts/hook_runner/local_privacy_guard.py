"""Pure command classification for operator-machine privacy boundaries.

The classifier names what a command would touch on the operator's machine and
nothing more; each consumer decides what that means for it. A live tool call
reads :mod:`local_privacy_messages`' severity map, which leaves personal-file
reads and GUI automation to the harness prompt and the operating system,
advises on broad home discovery, and refuses only the system privacy
database. The automated-test tripwire blocks every category instead, because
a unit test has no operator standing behind it to authorize anything.

The classifier is dependency-free so the full engine guard and the
product-local HTTPS fallback enforce one contract.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
import shlex
from pathlib import Path
from typing import Iterable, Sequence

from yoke_contracts.hook_runner.local_privacy_command_parse import (
    GREP_VALUE_OPTIONS,
    RG_VALUE_OPTIONS,
    option_positionals,
    segments,
    unwrap,
)
from yoke_contracts.hook_runner.local_privacy_messages import (
    HOME_DISCOVERY,
    LOCAL_GUI_AUTOMATION,
    PERSONAL_FILE_ACCESS,
    SYSTEM_PRIVACY_DATABASE,
    live_reason,
    live_severity,
    severity_rank,
    test_isolation_reason,
)


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
_GLOB_CHARS = frozenset("*?[")


@dataclass(frozen=True)
class LocalPrivacyFinding:
    """One command shape that touches the operator's machine, and what it is."""

    category: str
    target: str
    service: str

    @property
    def live_severity(self) -> str:
        """What a live tool call gets: ``deny``, ``advisory``, or ``allowed``."""
        return live_severity(self.category)

    def reason(self) -> str:
        """Live deny/advisory text. Raises for a category live callers allow."""
        return live_reason(self.category, self.target, self.service)

    def test_isolation_reason(self) -> str:
        """Text for the automated-test tripwire, which blocks every category."""
        return test_isolation_reason(self.category, self.target, self.service)


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


def _stronger(
    current: LocalPrivacyFinding | None, candidate: LocalPrivacyFinding | None
) -> LocalPrivacyFinding | None:
    """Return whichever finding a live caller must answer to.

    A command names several things, and the first one it names is not
    necessarily the one that matters: a personal-folder read the harness
    already authorized must never stand in for a privacy-database read later
    in the same command.
    """
    if candidate is None:
        return current
    if current is None:
        return candidate
    if severity_rank(candidate.category) > severity_rank(current.category):
        return candidate
    return current


def _names_one_file(parts: Sequence[str]) -> bool:
    """True when the operand names a single file rather than a tree to walk.

    ``rg pattern ~/Downloads/notes/spec.md`` is the operator handing over one
    document; ``rg pattern ~/Downloads`` is a search across everything they
    have downloaded. The filename extension is what separates them without
    asking the filesystem — and asking would be worse than imprecise here,
    since a stat against a protected folder answers from the very permission
    state the classification is reasoning about.
    """
    return bool(parts) and "." in parts[-1].lstrip(".")


def _protected_root(parts: Sequence[str]) -> tuple[str, ...] | None:
    for protected in _PROTECTED_HOME_ROOTS:
        if tuple(parts[: len(protected)]) == protected:
            return protected
    return None


def _path_finding(
    token: str,
    home: Path,
    cwd: str | os.PathLike[str] | None = None,
    *,
    discovery: bool = False,
) -> LocalPrivacyFinding | None:
    """Classify one path operand.

    ``discovery`` says the operand came from an enumeration tool (``find``,
    ``rg``, ``ls`` …) rather than a reader naming one file. That is the whole
    difference between "open the document the operator asked for" and "walk
    their folders looking for something", and the two get different answers
    live.
    """
    expanded = _expanded_path(token, home, cwd)
    if expanded is None:
        return None
    if expanded == str(_SYSTEM_PRIVACY_DATABASE) or expanded.startswith(
        str(_SYSTEM_PRIVACY_DATABASE.parent) + os.sep
    ):
        return LocalPrivacyFinding(SYSTEM_PRIVACY_DATABASE, token, "Full Disk Access")
    home_text = os.path.normpath(str(home))
    if expanded == home_text:
        return LocalPrivacyFinding(HOME_DISCOVERY, token, "user home")
    if not expanded.startswith(home_text + os.sep):
        return None
    relative = expanded[len(home_text) + 1 :]
    parts = tuple(part for part in relative.split(os.sep) if part)
    if parts and any(char in parts[0] for char in _GLOB_CHARS):
        return LocalPrivacyFinding(HOME_DISCOVERY, token, "user home")
    protected = _protected_root(parts)
    if protected is None:
        return None
    scope = "/".join(protected)
    globbed = any(char in part for part in parts for char in _GLOB_CHARS)
    if globbed or (discovery and not _names_one_file(parts)):
        return LocalPrivacyFinding(HOME_DISCOVERY, token, scope)
    return LocalPrivacyFinding(PERSONAL_FILE_ACCESS, token, scope)


def _implicit_scan(
    cwd: str | os.PathLike[str] | None, home: Path
) -> LocalPrivacyFinding | None:
    if cwd is None:
        return None
    return _path_finding(os.fspath(cwd), home, discovery=True)


def _strongest_path_finding(
    paths: Iterable[str],
    home: Path,
    cwd: str | os.PathLike[str] | None,
    *,
    discovery: bool = False,
) -> LocalPrivacyFinding | None:
    strongest: LocalPrivacyFinding | None = None
    for target in paths:
        strongest = _stronger(
            strongest, _path_finding(target, home, cwd, discovery=discovery)
        )
    return strongest


def _scan_segment(
    tokens: Sequence[str], *, home: Path, cwd: str | os.PathLike[str] | None
) -> LocalPrivacyFinding | None:
    executable, args = unwrap(tokens)
    if not executable:
        return None
    if executable in _LOCAL_AUTOMATION:
        return LocalPrivacyFinding(
            LOCAL_GUI_AUTOMATION, executable, _LOCAL_AUTOMATION[executable]
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
        return _strongest_path_finding(roots, home, cwd, discovery=True) or (
            _implicit_scan(cwd, home) if not roots else None
        )
    if executable in {"ls", "du", "tree"}:
        return _strongest_path_finding(
            (token for token in args if not token.startswith("-")),
            home,
            cwd,
            discovery=True,
        )
    if executable in {"fd", "fdfind"}:
        positionals = [token for token in args if not token.startswith("-")]
        paths = positionals[1:]
        return _strongest_path_finding(paths, home, cwd, discovery=True) or (
            _implicit_scan(cwd, home) if not paths else None
        )
    if executable in {"rg", "ripgrep"}:
        positionals, expression_supplied = option_positionals(args, RG_VALUE_OPTIONS)
        files_mode = "--files" in args
        paths = positionals if files_mode or expression_supplied else positionals[1:]
        return _strongest_path_finding(paths, home, cwd, discovery=True) or (
            _implicit_scan(cwd, home) if not paths else None
        )
    if executable in {"grep", "egrep", "fgrep"} and any(
        flag in args for flag in ("-r", "-R", "--recursive")
    ):
        positionals, expression_supplied = option_positionals(args, GREP_VALUE_OPTIONS)
        paths = positionals if expression_supplied else positionals[1:]
        return _strongest_path_finding(paths, home, cwd, discovery=True) or (
            _implicit_scan(cwd, home) if not paths else None
        )
    if executable in _DIRECT_READERS:
        return _strongest_path_finding(args, home, cwd)
    return None


def classify_shell_command(
    command: str,
    *,
    home: Path,
    cwd: str | os.PathLike[str] | None = None,
) -> LocalPrivacyFinding | None:
    """Return the strongest operator-machine privacy finding in ``command``."""
    strongest: LocalPrivacyFinding | None = None
    for segment in segments(command):
        strongest = _stronger(strongest, _scan_segment(segment, home=home, cwd=cwd))
    return strongest


def classify_subprocess_args(
    args: str | Sequence[object],
    *,
    home: Path,
    cwd: str | os.PathLike[str] | None = None,
) -> LocalPrivacyFinding | None:
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
    "LocalPrivacyFinding",
    "classify_shell_command",
    "classify_subprocess_args",
]
