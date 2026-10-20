"""Keep every test off the developer's real home folder.

Each test runs with ``HOME`` set to an empty per-test folder, and with the
variables that move a harness home or the XDG config root cleared, so every
resolver — ``Path.home()``, ``expanduser``, a harness path imported by name
into another module, and every subprocess the test starts — lands in that
folder. A test that needs a file a real home would hold (a git identity, a
machine config) writes it into the isolated home itself.

The session also fingerprints the real-home files Yoke's machine-wide setup
writes, before the first test and after the last. A changed fingerprint
fails the run and names the file, because a test that escaped the isolation
has already edited the developer's harness configuration.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Dict, Optional

import pytest

#: The variables, besides ``HOME``, that point a home resolver elsewhere.
HOME_REDIRECT_ENVS = ("XDG_CONFIG_HOME",)

_REAL_HOME_FINGERPRINT = pytest.StashKey[Dict[str, Optional[str]]]()


def isolated_home(tmp_path: Path) -> Path:
    """The per-test folder a test's ``HOME`` names."""
    return tmp_path / "harness-home"


def _redirect_envs() -> tuple:
    from yoke_contracts.harness_machine_hooks import HARNESS_MACHINE_HOOKS

    harness_envs = (spec.home_env for spec in HARNESS_MACHINE_HOOKS.values())
    return HOME_REDIRECT_ENVS + tuple(env for env in harness_envs if env)


@pytest.fixture(autouse=True)
def _isolate_real_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``HOME`` at an empty per-test folder for the whole test.

    The folder is not created: a harness counts as installed when its home
    exists, so a test creates the harness home it means to exercise.
    """
    home = isolated_home(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    for name in _redirect_envs():
        monkeypatch.delenv(name, raising=False)
    return home


@pytest.fixture(autouse=True)
def _isolate_harness_settings_ledger(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Keep the harness-settings record that uninstall reverts off ``~/.yoke``.

    Posture and folder-trust tests write throwaway harness configs; recording
    those paths in the developer's real record would aim a real uninstall at
    them. Subprocesses stay isolated through the ``YOKE_MACHINE_HOME`` they set.
    """
    from yoke_contracts import harness_settings_ledger

    monkeypatch.setattr(
        harness_settings_ledger,
        "ledger_path",
        lambda: tmp_path / "ledger" / harness_settings_ledger.LEDGER_NAME,
    )


def real_home_setup_files() -> tuple:
    """Every real-home file Yoke's machine-wide harness setup writes."""
    from yoke_contracts import harness_settings_ledger
    from yoke_contracts import harness_unattended_posture as posture
    from yoke_contracts.harness_machine_hooks import HARNESS_MACHINE_HOOKS

    hook_configs = (spec.user_config_path() for spec in HARNESS_MACHINE_HOOKS.values())
    return tuple(
        sorted(
            {
                *hook_configs,
                posture.codex_config_path(),
                posture.cursor_config_path(),
                posture.claude_settings_path(),
                posture.claude_config_path(),
                harness_settings_ledger.ledger_path(),
            }
        )
    )


def fingerprint(paths) -> Dict[str, Optional[str]]:
    """Each path's content digest, or ``None`` while it does not exist."""
    prints: Dict[str, Optional[str]] = {}
    for path in paths:
        try:
            prints[str(path)] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        except FileNotFoundError:
            prints[str(path)] = None
    return prints


def changed_files(before, after) -> list:
    """The paths whose fingerprint differs between two readings."""
    return sorted(path for path in before if before[path] != after.get(path))


def real_home_violation(changed) -> str:
    """The failure a run reports when it changed a real-home setup file."""
    listing = "\n".join(f"  {path}" for path in changed)
    return (
        "real_home_written: the test run changed these files in the real home:\n"
        f"{listing}\n"
        "A test resolved the developer's home instead of its isolated HOME. "
        "Find it by re-running the suspect modules with `-p no:xdist`, compare "
        "each file against its version control or backup, and restore it. If "
        "another live harness session on this machine rewrote the file, "
        "re-run the suite."
    )


def _is_controller(config: pytest.Config) -> bool:
    return not hasattr(config, "workerinput")


def pytest_sessionstart(session: pytest.Session) -> None:
    if _is_controller(session.config) and os.environ.get("HOME"):
        session.config.stash[_REAL_HOME_FINGERPRINT] = fingerprint(
            real_home_setup_files()
        )


def pytest_sessionfinish(session: pytest.Session) -> None:
    before = session.config.stash.get(_REAL_HOME_FINGERPRINT, None)
    if before is None:
        return
    changed = changed_files(before, fingerprint(before))
    if not changed:
        return
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    message = real_home_violation(changed)
    if reporter is not None:
        reporter.write_line(message, red=True)
    else:
        print(message)
    session.exitstatus = pytest.ExitCode.TESTS_FAILED
