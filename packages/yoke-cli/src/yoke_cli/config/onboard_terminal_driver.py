"""Setup's terminal geometry and POSIX job-control safety around Textual.

The input thread blocks SIGTTIN so a racing background read returns EIO
instead of stopping the process with raw/mouse modes active. Startup and
restoration use scoped signal masks; no signal is ignored and terminal
ownership is never changed.
"""

from __future__ import annotations

import errno
import os
import signal
import subprocess
import sys
from contextlib import contextmanager

from yoke_cli import terminal_detached_process
from yoke_cli.config.onboard_terminal import (
    SetupTerminalError,
    require_foreground_terminal,
    wizard_owns_terminal,
)

OWNERSHIP_CHECK_SECONDS = 0.1
STATIC_GEOMETRY_VARIABLES = ("COLUMNS", "LINES")


@contextmanager
def _blocked(signals):
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, signals)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


@contextmanager
def live_terminal_geometry():
    """Hide exported COLUMNS/LINES so every size read asks the terminal.

    Textual's POSIX driver and Rich's Windows startup size both prefer these
    variables over the console. A value exported before a window resize pins
    the wizard to the old geometry: frames taller than the window scroll it,
    the step header disappears, and earlier screens stay visible.
    """
    saved = {
        name: os.environ.pop(name)
        for name in STATIC_GEOMETRY_VARIABLES
        if name in os.environ
    }
    try:
        yield
    finally:
        os.environ.update(saved)


def _loss_cause(evidence: dict) -> str:
    """Name what the ownership check saw: signal, foreground group, errno."""
    parts = []
    if "signal" in evidence:
        parts.append(signal.Signals(evidence["signal"]).name)
    if "errno" in evidence:
        code = evidence["errno"]
        parts.append(f"terminal check errno {code} ({errno.errorcode.get(code, '?')})")
    foreground = evidence.get("foreground")
    if foreground is not None and foreground != os.getpgrp():
        command = _group_leader_command(foreground)
        parts.append(
            f"terminal foreground process group {foreground}"
            + (f" ({command})" if command else "")
            + f", setup's group {os.getpgrp()}"
        )
    return "; ".join(parts) or "no further evidence"


def _group_leader_command(group: int) -> str:
    # The leader may already have exited and handed the terminal back.
    try:
        result = terminal_detached_process.run(
            ["ps", "-o", "command=", "-p", str(group)],
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return " ".join(result.stdout.split())[:200]


def run_wizard_app(app) -> None:
    """Run the wizard against the terminal's live geometry."""
    with live_terminal_geometry(), wizard_owns_terminal():
        _run_with_platform_driver(app)


def _run_with_platform_driver(app) -> None:
    """Use the native Windows lifecycle or the guarded POSIX driver."""
    if os.name == "nt":
        app.run()
        return
    require_foreground_terminal(sys.__stdin__)
    from textual.drivers.linux_driver import LinuxDriver

    import termios

    lost = False
    evidence: dict = {}
    startup_error = None
    restore_error = None
    job_signals = {signal.SIGTTIN, signal.SIGTTOU}
    saved_handlers = {sig: signal.getsignal(sig) for sig in job_signals}

    class SetupDriver(LinuxDriver):
        """Keep Textual's suspend/resume and restore before a job-control exit."""

        active = False
        ownership_check = None
        ownership_signal = False

        def ownership_lost(self, signum=None, *_):
            nonlocal lost, restore_error
            if lost:
                return
            if signum is not None:
                evidence.setdefault("signal", signum)
                self.observe_foreground()
            if signum is not None and self.active:
                # A signal can interrupt a write holding Textual's queue lock.
                # The existing timer performs cleanup outside that call stack.
                self.ownership_signal = True
                return
            lost = True
            # A signal may interrupt a copy handoff's blocking input, so restore
            # immediately rather than waiting for the app's event loop to run.
            with _blocked({signal.SIGTTOU}):
                try:
                    if self.attrs_before is not None:
                        termios.tcsetattr(
                            self.fileno, termios.TCSANOW, self.attrs_before
                        )
                    self._disable_mouse_support()
                    if self._mouse_pixels:
                        self.write("\x1b[?1016l")
                    self.flush()
                except (OSError, termios.error) as exc:
                    restore_error = str(exc)
            self._app.exit()
            if signum == signal.SIGTTIN and not self.active:
                # The suspended copy view catches OSError. Break input() rather
                # than letting Python restart a background read indefinitely.
                raise OSError("setup_terminal_ownership_lost")

        def observe_foreground(self):
            try:
                foreground = os.tcgetpgrp(self.fileno)
            except OSError as exc:
                evidence.setdefault("errno", exc.errno)
                return None
            if foreground != os.getpgrp():
                evidence.setdefault("foreground", foreground)
            return foreground

        def check_ownership(self):
            if not self.active or lost:
                return
            if self.ownership_signal:
                self.ownership_lost()
                return
            foreground = self.observe_foreground()
            if foreground != os.getpgrp():
                self.ownership_lost()
                return
            self.ownership_check = self._loop.call_later(
                OWNERSHIP_CHECK_SECONDS, self.check_ownership
            )

        def start_application_mode(self):
            nonlocal lost, startup_error
            if lost:
                return
            try:
                require_foreground_terminal(sys.__stdin__)
            except SetupTerminalError as exc:
                lost, startup_error = True, exc
                self._app.exit()
                return
            # Textual resets job-control handlers during startup. Defer those
            # signals until our scoped handlers are installed, including the
            # race between ownership validation and enabling terminal modes.
            with _blocked(job_signals):
                super().start_application_mode()
                for sig in job_signals:
                    signal.signal(sig, self.ownership_lost)
                self.active = True
                self.check_ownership()

        def run_input_thread(self):
            with _blocked({signal.SIGTTIN}):
                try:
                    super().run_input_thread()
                except OSError as exc:
                    foreground = self.observe_foreground()
                    if lost or foreground != os.getpgrp():
                        evidence.setdefault("errno", exc.errno)
                        self._loop.call_soon_threadsafe(self.ownership_lost)
                    else:
                        raise

        def stop_application_mode(self):
            self.active = False
            if self.ownership_check is not None:
                self.ownership_check.cancel()
            if self._writer_thread is None:
                return  # ownership was refused before application mode
            # POSIX permits restoring our saved attributes while SIGTTOU is
            # locally blocked, even after another process group owns the tty.
            with _blocked(job_signals):
                if self._mouse_pixels:
                    self.write("\x1b[?1016l")
                super().stop_application_mode()

    original_driver = app.driver_class
    app.driver_class = SetupDriver
    try:
        app.run()
    finally:
        app.driver_class = original_driver
        for sig, handler in saved_handlers.items():
            signal.signal(sig, handler)
    if startup_error:
        raise SetupTerminalError(
            "setup_terminal_ownership_lost: ownership changed before the wizard "
            "started. Return to the foreground shell and run `yoke setup` again."
        ) from startup_error
    if lost:
        recovery = "Return to the foreground shell and run `yoke setup` again."
        if restore_error:
            recovery = f"Terminal restoration failed ({restore_error}); run `stty sane`, then `yoke setup`."
        raise SetupTerminalError(
            f"setup_terminal_ownership_lost: setup stopped "
            f"({_loss_cause(evidence)}). {recovery}"
        )
