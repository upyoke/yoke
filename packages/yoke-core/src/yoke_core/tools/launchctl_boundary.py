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

from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time
from typing import Any, Callable

from yoke_cli.config.machine_config import default_yoke_home
from yoke_cli.config.session_relay_instance import PROD_RELAY_LABEL


CANONICAL_RELAY_LABEL = PROD_RELAY_LABEL
CANONICAL_RELAY_PLIST_NAME = f"{PROD_RELAY_LABEL}.plist"
LAUNCH_AGENTS_DIR_NAME = "LaunchAgents"
JOURNAL_NAME = "launchctl-journal.jsonl"
UNLOAD_POLL_ATTEMPTS = 10
UNLOAD_POLL_INTERVAL_SECONDS = 0.05

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
        if text == CANONICAL_RELAY_LABEL or text.endswith(f"/{CANONICAL_RELAY_LABEL}"):
            return True
        if Path(text).name == CANONICAL_RELAY_PLIST_NAME:
            return True
    return False


def launch_agents_home(
    home: Path | None = None,
    *,
    yoke_home: Path | None = None,
) -> Path:
    """Return the user-home whose ``Library/LaunchAgents`` may be written.

    An isolated machine-home — anything other than the default
    ``<user-home>/.yoke`` — keeps LaunchAgents inside itself so a pytest
    sandbox can never write the operator's login domain. An explicit
    ``home`` still wins, for tests that already pass a disposable root.
    """
    if home is not None:
        return Path(home).expanduser()
    if yoke_home is None:
        return Path.home()
    isolated = Path(yoke_home).expanduser().resolve(strict=False)
    if isolated == default_yoke_home().expanduser().resolve(strict=False):
        return Path.home()
    return isolated


def launch_agents_dir(
    home: Path | None = None,
    *,
    environ: Mapping[str, str] | None = None,
    yoke_home: Path | None = None,
) -> Path:
    """Resolve where launch-agent plists belong for this process.

    A test that passes its own home already writes somewhere disposable and
    is left alone. An isolated machine-home is treated the same way: its
    LaunchAgents directory stays inside that sandbox. Only the operator's
    real ``~/Library/LaunchAgents`` is redirected into the test sandbox.
    """
    resolved = launch_agents_home(home, yoke_home=yoke_home).resolve(strict=False)
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
        f"a test process may not run launchctl: {' '.join(resolved)}. " + _RECOVERY
    )


def wait_for_launchd_unload(
    target: str,
    *,
    run: Callable[[Sequence[str]], subprocess.CompletedProcess[str]],
    pause: Callable[[float], None] = time.sleep,
) -> bool:
    """Poll until launchd no longer reports the exact job as loaded."""
    for attempt in range(UNLOAD_POLL_ATTEMPTS):
        if run(["launchctl", "print", target]).returncode != 0:
            return True
        if attempt + 1 < UNLOAD_POLL_ATTEMPTS:
            pause(UNLOAD_POLL_INTERVAL_SECONDS)
    return False


def bootstrap_launchd_job(
    domain: str,
    plist: Path,
    *,
    run: Callable[[Sequence[str]], subprocess.CompletedProcess[str]],
) -> subprocess.CompletedProcess[str]:
    """Bootstrap once, retrying only launchd's known transient I/O refusal."""
    command = ["launchctl", "bootstrap", domain, str(plist)]
    result = run(command)
    detail = f"{result.stderr or ''}\n{result.stdout or ''}".casefold()
    if (
        result.returncode
        and "bootstrap failed: 5:" in detail
        and "input/output error" in detail
    ):
        return run(command)
    return result


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


@contextmanager
def integration_domain(env: Any, *, marked: bool) -> Iterator[Callable[[str], None]]:
    """Lend a marked test the real launchd domain, and take it back after.

    ``env`` is any pytest ``monkeypatch``-shaped object: the opt-in has to
    be an environment variable so a spawned child inherits it, and undoing
    it belongs to whoever set it. Yields a callable that registers a label
    for unconditional bootout when the test ends, however it ends.
    """
    if not marked:
        raise LaunchdBoundaryError(
            "loading a real launchd job requires the `launchd_integration` "
            "marker, so every test that touches the real domain stays "
            "greppable. Mark the test, or stub the launchctl runner."
        )
    env.delenv(SANDBOX_ENV, raising=False)
    env.setenv(REAL_LAUNCHD_OPT_IN_ENV, "1")
    loaded: list[str] = []
    try:
        yield loaded.append
    finally:
        bootout_labels(loaded)


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
    "bootstrap_launchd_job",
    "integration_domain",
    "launch_agents_dir",
    "launch_agents_home",
    "launchd_target",
    "names_canonical_relay",
    "real_launchd_opted_in",
    "recorded_commands",
    "run_launchctl",
    "sandbox_root",
    "under_test",
    "wait_for_launchd_unload",
]
