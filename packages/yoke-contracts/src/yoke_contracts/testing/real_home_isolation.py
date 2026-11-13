"""Keep every test off the developer's real home folder.

Each test runs with ``HOME`` set to an empty per-test folder, and with the
variables that move a harness home or the XDG config root cleared, so every
resolver — ``Path.home()``, ``expanduser``, a harness path imported by name
into another module, and every subprocess the test starts — lands in that
folder. A test that needs a file a real home would hold (a git identity, a
machine config) writes it into the isolated home itself.

A path captured before the test started (a module constant built from
``Path.home()`` at import, a fixture that pins a machine folder) still names
the real home. So a Python audit hook watches every write the test's own
process makes while the test runs, and fails the test with
``real_home_written`` naming each real-home path it created, changed or
removed. The checkout (pytest's rootpath and the folder it was invoked
from), its environment and the interpreter are exempt: they often live inside
the home folder and tests legitimately write them. An exempt root that is or
holds the home itself is dropped, so pytest run from the home stays guarded.

Any project loads it from its root ``conftest.py``::

    pytest_plugins = ["yoke_contracts.testing.real_home_isolation"]
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
from typing import Iterable, List, Sequence, Tuple

import pytest

#: The variables, besides ``HOME``, that point a home resolver elsewhere.
HOME_REDIRECT_ENVS = ("XDG_CONFIG_HOME",)

#: Audit events that write the filesystem: each written path's argument
#: position, paired with the position of the ``dir_fd`` it is relative to
#: (``None`` when the event carries none). ``open`` is judged separately by its
#: mode; its audit event never carries a ``dir_fd``.
WRITE_EVENTS = {
    "os.chmod": ((0, 2),),
    "os.link": ((1, 3),),
    "os.mkdir": ((0, 2),),
    "os.remove": ((0, 1),),
    "os.rename": ((0, 2), (1, 3)),
    "os.rmdir": ((0, 1),),
    "os.symlink": ((1, 2),),
    "os.truncate": ((0, None),),
    "os.utime": ((0, 3),),
    "shutil.copyfile": ((1, None),),
    "shutil.copytree": ((1, None),),
    "shutil.rmtree": ((0, None),),
}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def _written_by_open(args: Sequence[object]) -> bool:
    mode = args[1] if len(args) > 1 else None
    flags = args[2] if len(args) > 2 else 0
    if isinstance(mode, str) and any(char in mode for char in "wax+"):
        return True
    return isinstance(flags, int) and bool(flags & _WRITE_FLAGS)


def _under(path: str, root: str) -> bool:
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


class RealHomeWriteGuard:
    """Record the real-home writes one process makes while a test runs."""

    def __init__(self, home: Path, exempt: Iterable[Path] = ()) -> None:
        self.home = str(home)
        self.exempt: Tuple[str, ...] = tuple(str(path) for path in exempt)
        self.active = False
        self.writes: List[Tuple[str, str]] = []

    def _record(self, event: str, target: object) -> None:
        if isinstance(target, int) or target is None:
            return
        try:
            path = os.path.abspath(os.fsdecode(os.fspath(target)))
        except (TypeError, ValueError):
            return
        if _under(path, self.home) and not any(
            _under(path, root) for root in self.exempt
        ):
            self.writes.append((event, path))

    def audit(self, event: str, args: Sequence[object]) -> None:
        if not self.active:
            return
        if event == "open":
            if args and _written_by_open(args):
                self._record(event, args[0])
            return
        for position, fd_position in WRITE_EVENTS.get(event, ()):
            if position >= len(args):
                continue
            # A path relative to an open folder is not relative to the cwd.
            # Only shutil.rmtree's fd walk writes this way, and rmtree itself
            # is audited with its top-level path, so skipping it hides nothing.
            if fd_position is not None and fd_position < len(args):
                if args[fd_position] not in (None, -1):
                    continue
            self._record(event, args[position])

    def start(self) -> None:
        self.writes = []
        self.active = True

    def stop(self) -> List[Tuple[str, str]]:
        self.active = False
        return list(self.writes)


#: The process-wide guard; its real home is read before any test changes it.
GUARD = RealHomeWriteGuard(Path(os.path.expanduser("~")))
sys.addaudithook(GUARD.audit)


def real_home_violation(writes: Sequence[Tuple[str, str]]) -> str:
    """The failure a test reports when it wrote the developer's real home."""
    listing = "\n".join(f"  {event}: {path}" for event, path in sorted(set(writes)))
    return (
        "real_home_written: this test wrote the developer's real home:\n"
        f"{listing}\n"
        "The path was resolved before the test's isolated HOME took effect, "
        "usually a module constant built from Path.home() at import or a "
        "fixture that pins a machine folder. Resolve the path at call time, "
        "or point the fixture inside tmp_path, then restore the named file."
    )


def exempt_roots(
    home: str, roots: Iterable["str | os.PathLike[str]"]
) -> Tuple[str, ...]:
    """The roots a test may write, minus any that is or holds the real home.

    A root at or above the home (pytest run from ``$HOME``) would exempt the
    whole home and switch the guard off, so it is dropped.
    """
    kept: List[str] = []
    for root in roots:
        path = os.path.abspath(os.fspath(root))
        if not _under(home, path) and path not in kept:
            kept.append(path)
    return tuple(kept)


def pytest_configure(config: pytest.Config) -> None:
    # The checkout is the folder pytest is invoked from, which need not be its
    # rootpath (a config file in a service folder). The interpreter may itself
    # live under the home folder (a uv-managed Python), and a lazy import
    # writes bytecode beside its standard library.
    GUARD.exempt = exempt_roots(
        GUARD.home,
        (
            config.rootpath,
            config.invocation_params.dir,
            sys.prefix,
            sys.base_prefix,
        ),
    )


def isolated_home(tmp_path: Path) -> Path:
    """The per-test folder a test's ``HOME`` names."""
    return tmp_path / "harness-home"


def _redirect_envs() -> tuple:
    from yoke_contracts.harness_machine_hooks import HARNESS_MACHINE_HOOKS

    harness_envs = (spec.home_env for spec in HARNESS_MACHINE_HOOKS.values())
    return HOME_REDIRECT_ENVS + tuple(env for env in harness_envs if env)


@pytest.fixture(autouse=True)
def _isolate_real_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point ``HOME`` at an empty per-test folder and fail real-home writes.

    The folder is not created: a harness counts as installed when its home
    exists, so a test creates the harness home it means to exercise.
    """
    home = isolated_home(tmp_path)
    monkeypatch.setenv("HOME", str(home))
    for name in _redirect_envs():
        monkeypatch.delenv(name, raising=False)
    GUARD.start()
    yield home
    writes = GUARD.stop()
    if writes:
        pytest.fail(real_home_violation(writes), pytrace=False)


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
