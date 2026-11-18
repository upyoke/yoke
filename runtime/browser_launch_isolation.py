"""Fail any test that would open a real browser on the operator's machine.

A browser-opening code path under test must receive an explicit fake. Three
routes reach a real browser and each is closed here:

* :mod:`webbrowser`'s module-level openers, replaced by a failing stub;
* a native launcher started as a subprocess (``open``, ``xdg-open``,
  ``wslview``, PowerShell ``Start-Process``, ``cmd /c start`` and the Debian
  alternatives), refused before the process exists;
* ``os.startfile`` where the platform has it.

``BROWSER`` covers child Python processes: its command records the URL and
exits successfully, so a child's :mod:`webbrowser` never reaches the default
browser and the attempt still fails the test at teardown.

Every refusal names the test and the launcher so the fix is obvious: inject
a fake opener and assert the requested URL instead. A fake launcher the test
wrote under its own ``tmp_path`` and runs by absolute path is allowed.
"""

from __future__ import annotations

import os
from pathlib import Path, PurePath, PureWindowsPath
import shlex
import subprocess
import sys

import pytest


NATIVE_BROWSER_LAUNCHERS = frozenset(
    {
        "open",
        "xdg-open",
        "wslview",
        "sensible-browser",
        "x-www-browser",
        "www-browser",
        "gnome-open",
        "kde-open",
    }
)
_WINDOWS_SHELLS = frozenset({"cmd", "cmd.exe"})
_POWERSHELLS = frozenset({"powershell", "powershell.exe", "pwsh", "pwsh.exe"})


def native_browser_launcher(args: object) -> str | None:
    """Name the native browser launcher *args* would start, if any."""
    if isinstance(args, (str, bytes, os.PathLike)):
        text = os.fsdecode(args)
        try:
            argv = shlex.split(text)
        except ValueError:
            argv = text.split()
    else:
        try:
            argv = [os.fsdecode(part) for part in args]  # type: ignore[union-attr]
        except TypeError:
            return None
    if not argv:
        return None
    program = PureWindowsPath(PurePath(argv[0]).name).name.lower()
    if program in NATIVE_BROWSER_LAUNCHERS:
        return program
    if program in _WINDOWS_SHELLS and any(a.lower() == "start" for a in argv[1:]):
        return "cmd start"
    if program in _POWERSHELLS and any(
        "start-process" in a.lower() for a in argv[1:]
    ):
        return "powershell Start-Process"
    return None


def _refusal(nodeid: str, launcher: str) -> str:
    return (
        f"{nodeid} tried to open a real browser through {launcher}. "
        "Automated tests may not launch the operator's browser; inject a fake "
        "opener (for example browser_open=..., or monkeypatch the caller's "
        "open_url) and assert the requested URL instead."
    )


def _test_owned_program(args: object, root: Path) -> bool:
    """Whether *args* runs a fake launcher the test wrote under *root*."""
    if isinstance(args, (str, bytes, os.PathLike)):
        return False
    try:
        program = Path(os.fsdecode(next(iter(args))))  # type: ignore[call-overload]
    except (StopIteration, TypeError):
        return False
    return program.is_absolute() and program.resolve().is_relative_to(root.resolve())


class BrowserLaunchGuard:
    """Refuse every real-browser route for one test and remember the attempts."""

    def __init__(self, nodeid: str, child_attempt: Path) -> None:
        self.nodeid = nodeid
        self.child_attempt = child_attempt
        self.attempts: list[str] = []

    def refuse(self, launcher: str):
        self.attempts.append(launcher)
        pytest.fail(_refusal(self.nodeid, launcher))

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import webbrowser

        def _fail_webbrowser(*_args, **_kwargs):
            self.refuse("webbrowser.open")

        monkeypatch.setattr(webbrowser, "open", _fail_webbrowser)
        monkeypatch.setattr(webbrowser, "open_new", _fail_webbrowser)
        monkeypatch.setattr(webbrowser, "open_new_tab", _fail_webbrowser)
        if hasattr(os, "startfile"):
            monkeypatch.setattr(
                os, "startfile", lambda *a, **k: self.refuse("os.startfile")
            )
        guard = self

        # A subclass rather than a wrapping function keeps ``subprocess.Popen``
        # subscriptable for modules that annotate with it, and composes with
        # the other autouse guards that subclass whichever Popen they find.
        class _BrowserGuardedPopen(subprocess.Popen):
            def __init__(self, *popen_args, **kwargs):
                args = popen_args[0] if popen_args else kwargs.get("args", ())
                launcher = native_browser_launcher(args)
                if launcher is not None and not _test_owned_program(
                    args, guard.child_attempt.parent
                ):
                    guard.refuse(launcher)
                super().__init__(*popen_args, **kwargs)

        monkeypatch.setattr(subprocess, "Popen", _BrowserGuardedPopen)
        monkeypatch.setenv(
            "BROWSER",
            shlex.join(
                [
                    sys.executable,
                    "-c",
                    "from pathlib import Path; import sys; Path(sys.argv[1]).touch()",
                    str(self.child_attempt),
                    "%s",
                ]
            ),
        )

    def verdict(self) -> str | None:
        """The teardown refusal, when any route was attempted."""
        attempts = list(self.attempts)
        if self.child_attempt.exists():
            attempts.append("a child process's webbrowser")
        return _refusal(self.nodeid, ", ".join(attempts)) if attempts else None


@pytest.fixture(autouse=True)
def _forbid_real_browser_launches(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    guard = BrowserLaunchGuard(
        request.node.nodeid, tmp_path / "unexpected-browser-launch"
    )
    guard.install(monkeypatch)
    yield
    refusal = guard.verdict()
    if refusal is not None:
        pytest.fail(refusal)
