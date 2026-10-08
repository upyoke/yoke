"""Setup's POSIX job-control safety around Textual's terminal lifecycle.

The input thread blocks SIGTTIN so a racing background read returns EIO
instead of stopping the process with raw/mouse modes active. Startup and
restoration use scoped signal masks; no signal is ignored and terminal
ownership is never changed.
"""

from __future__ import annotations

import os
import signal
import sys
from contextlib import contextmanager

from yoke_cli.config.onboard_terminal import (
    SetupTerminalError,
    require_foreground_terminal,
)

OWNERSHIP_CHECK_SECONDS = 0.1


@contextmanager
def _blocked(signals):
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, signals)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)


def run_wizard_app(app) -> None:
    """Use the native Windows lifecycle or the guarded POSIX driver."""
    if os.name == "nt":
        app.run()
        return
    require_foreground_terminal(sys.__stdin__)
    from textual.drivers.linux_driver import LinuxDriver

    import termios

    lost = False
    startup_error = None
    restore_error = None
    job_signals = {signal.SIGTTIN, signal.SIGTTOU}
    saved_handlers = {sig: signal.getsignal(sig) for sig in job_signals}

    class SetupDriver(LinuxDriver):
        """Keep Textual's suspend/resume and restore before a job-control exit."""

        active = False
        ownership_check = None

        def ownership_lost(self, signum=None, *_):
            nonlocal lost, restore_error
            if lost:
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

        def check_ownership(self):
            if not self.active or lost:
                return
            try:
                foreground = os.tcgetpgrp(self.fileno)
            except OSError:
                self.ownership_lost()
                return
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
                except OSError:
                    try:
                        foreground = os.tcgetpgrp(self.fileno)
                    except OSError:
                        foreground = None
                    if lost or foreground != os.getpgrp():
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
            with _blocked({signal.SIGTTOU}):
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
            f"setup_terminal_ownership_lost: setup stopped. {recovery}"
        )
