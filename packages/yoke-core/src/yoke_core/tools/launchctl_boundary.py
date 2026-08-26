"""The one boundary through which Yoke may reach the real launchd domain.

Every launchctl invocation and every launch-agent plist location resolves
here, because a unique label is not isolation: a job named for a throwaway
config still loads into the operator's real login domain, notifies them,
and outlives the process that registered it. Under an automated test this
boundary either records the command into a per-test sandbox or refuses it
by name, and it never lets a test touch the canonical relay the machine's
whole fleet depends on.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

from yoke_cli.config.session_relay_instance import PROD_RELAY_LABEL


CANONICAL_RELAY_LABEL = PROD_RELAY_LABEL
CANONICAL_RELAY_PLIST_NAME = f"{PROD_RELAY_LABEL}.plist"
LAUNCH_AGENTS_DIR_NAME = "LaunchAgents"
JOURNAL_NAME = "launchctl-journal.jsonl"

#: Directory a test process lends this boundary: launch-agent plists are
#: written under it and launchctl commands are recorded into its journal
#: instead of being executed. The repo-wide conftest sets one per test.
SANDBOX_ENV = "YOKE_LAUNCHD_TEST_SANDBOX"

#: Set only by the ``real_launchd_agent`` fixture, for a marked integration
#: test that genuinely has to load an agent. It never covers the canonical
#: relay label.
REAL_LAUNCHD_OPT_IN_ENV = "YOKE_TEST_ALLOW_REAL_LAUNCHD"

_RECOVERY = (
    "Stub the launchctl runner (every relay entry point takes a `runner`), "
    "assert the plist document instead of loading it, or — for a test that "
    "must load a real agent — mark it `launchd_integration` and request the "
    "`real_launchd_agent` fixture, which boots the label out in teardown."
)


class LaunchdBoundaryError(RuntimeError):
    """A launchd operation was refused before it could reach the real domain."""


def _environ(environ: Mapping[str, str] | None) -> Mapping[str, str]:
    return os.environ if environ is None else environ


def under_test(environ: Mapping[str, str] | None = None) -> bool:
    """Report whether this process is running as, or underneath, a test.

    ``PYTEST_CURRENT_TEST`` is the half that crosses a process boundary:
    a child the test spawns inherits it, and the leaks this boundary
    exists to stop were registered by exactly such a child.
    """
    source = _environ(environ)
    return bool(str(source.get("PYTEST_CURRENT_TEST") or "").strip()) or (
        "pytest" in sys.modules
    )


def sandbox_root(environ: Mapping[str, str] | None = None) -> Path | None:
    raw = str(_environ(environ).get(SANDBOX_ENV) or "").strip()
    return Path(raw).expanduser() if raw else None


def real_launchd_opted_in(environ: Mapping[str, str] | None = None) -> bool:
    return bool(str(_environ(environ).get(REAL_LAUNCHD_OPT_IN_ENV) or "").strip())


def launchd_target(label: str, uid: int | None = None) -> str:
    return f"gui/{os.getuid() if uid is None else uid}/{label}"


def names_canonical_relay(command: Sequence[str]) -> bool:
    """Report whether a launchctl command addresses the machine's live relay."""
    for argument in command:
        text = str(argument)
        if text == CANONICAL_RELAY_LABEL or text.endswith(
            f"/{CANONICAL_RELAY_LABEL}"
        ):
            return True
        if Path(text).name == CANONICAL_RELAY_PLIST_NAME:
            return True
    return False


def launch_agents_dir(
    home: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve where launch-agent plists belong for this process.

    A test that passes its own home already writes somewhere disposable and
    is left alone. Only the operator's real ``~/Library/LaunchAgents`` is
    redirected into the test sandbox, so a test can exercise the installer
    end to end without leaving a plist behind on the machine.
    """
    resolved = (home or Path.home()).expanduser().resolve(strict=False)
    real_home = Path.home().expanduser().resolve(strict=False)
    if resolved != real_home or not under_test(environ):
        return resolved / "Library" / LAUNCH_AGENTS_DIR_NAME
    sandbox = sandbox_root(environ)
    if sandbox is None:
        raise LaunchdBoundaryError(
            "a test process may not write a launch-agent plist into the "
            f"operator's real {real_home / 'Library' / LAUNCH_AGENTS_DIR_NAME}. "
            + _RECOVERY
        )
    return sandbox / LAUNCH_AGENTS_DIR_NAME


def run_launchctl(
    command: Sequence[str],
    *,
    check: bool = False,
    capture_output: bool = True,
    text: bool = True,
    environ: Mapping[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run one launchctl command, or refuse it by name from a test process."""
    resolved = [str(part) for part in command]
    if not under_test(environ):
        return subprocess.run(
            resolved,
            check=check,
            capture_output=capture_output,
            text=text,
        )
    sandbox = sandbox_root(environ)
    if sandbox is not None:
        return _record_and_simulate(sandbox, resolved)
    if real_launchd_opted_in(environ):
        if names_canonical_relay(resolved):
            raise LaunchdBoundaryError(
                f"the canonical machine relay ({CANONICAL_RELAY_LABEL}) serves "
                "the whole fleet and is never installed, loaded, or booted out "
                f"from a test process: {' '.join(resolved)}. Point the test at a "
                "per-environment label instead. If an earlier run already "
                "unloaded it, `yoke relay install` reloads it."
            )
        return subprocess.run(
            resolved,
            check=check,
            capture_output=capture_output,
            text=text,
        )
    raise LaunchdBoundaryError(
        f"a test process may not run launchctl: {' '.join(resolved)}. "
        + _RECOVERY
    )


def recorded_commands(sandbox: Path) -> list[list[str]]:
    """Return the launchctl commands a sandboxed process asked for, in order."""
    journal = sandbox / JOURNAL_NAME
    if not journal.is_file():
        return []
    recorded: list[list[str]] = []
    for line in journal.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        command = entry.get("command")
        if isinstance(command, list):
            recorded.append([str(part) for part in command])
    return recorded


def bootout_labels(
    labels: Iterable[str],
    *,
    uid: int | None = None,
    environ: Mapping[str, str] | None = None,
) -> None:
    """Unload every named job, whatever the test that loaded them did."""
    for label in labels:
        run_launchctl(
            ["launchctl", "bootout", launchd_target(label, uid)],
            environ=environ,
        )


def _record_and_simulate(
    sandbox: Path,
    command: list[str],
) -> subprocess.CompletedProcess[str]:
    journal = sandbox / JOURNAL_NAME
    journal.parent.mkdir(parents=True, exist_ok=True)
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"command": command}) + "\n")
    verb = command[1] if len(command) > 1 else ""
    returncode = 0
    if verb == "print":
        returncode = 0 if command[-1] in _loaded_targets(sandbox) else 1
    return subprocess.CompletedProcess(command, returncode, "", "")


def _loaded_targets(sandbox: Path) -> set[str]:
    loaded: set[str] = set()
    for command in recorded_commands(sandbox):
        verb = command[1] if len(command) > 1 else ""
        if verb == "bootout":
            loaded.discard(command[-1])
        elif verb == "bootstrap" and len(command) >= 4:
            label = _plist_label(Path(command[-1]))
            if label:
                loaded.add(f"{command[-2]}/{label}")
    return loaded


def _plist_label(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            document = plistlib.load(handle)
    except (OSError, ValueError, plistlib.InvalidFileException):
        return ""
    return str(document.get("Label") or "")


__all__ = [
    "CANONICAL_RELAY_LABEL",
    "CANONICAL_RELAY_PLIST_NAME",
    "JOURNAL_NAME",
    "LaunchdBoundaryError",
    "REAL_LAUNCHD_OPT_IN_ENV",
    "SANDBOX_ENV",
    "bootout_labels",
    "launch_agents_dir",
    "launchd_target",
    "names_canonical_relay",
    "real_launchd_opted_in",
    "recorded_commands",
    "run_launchctl",
    "sandbox_root",
    "under_test",
]
