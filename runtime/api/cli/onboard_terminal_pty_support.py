"""Isolated controlling terminals for setup job-control regressions.

The controller and wizard are disposable children in their own session. No
operator terminal, setup configuration, browser, or control plane is touched.
"""

from __future__ import annotations

import errno
import json
import os
import selectors
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace


def run_pty(scenario: str, tmp_path: Path) -> tuple[str, dict]:
    import pty

    master, slave = pty.openpty()
    evidence = tmp_path / "result.json"
    env = {**os.environ, "TERM": "xterm-256color"}
    process = subprocess.Popen(
        [sys.executable, "-m", __name__, str(slave), scenario, str(evidence)],
        pass_fds=(slave,),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = bytearray()
    selector = selectors.DefaultSelector()
    selector.register(master, selectors.EVENT_READ)
    deadline = time.monotonic() + 20
    returned_from_copy = False
    try:
        while process.poll() is None and time.monotonic() < deadline:
            for _key, _mask in selector.select(0.1):
                output.extend(os.read(master, 65536))
            if b"Press Enter to return" in output and not returned_from_copy:
                os.write(master, b"\n")
                returned_from_copy = True
        assert process.poll() is not None, (
            "isolated setup terminal timed out: "
            + output[-4000:].decode(errors="replace")
        )
        # Drain bytes queued by the terminal's writer before reading its modes.
        while selector.select(0):
            try:
                data = os.read(master, 65536)
            except OSError as exc:
                if exc.errno == errno.EIO:
                    break
                raise
            if not data:
                break
            output.extend(data)
        controller_output = process.communicate()[0].decode(errors="replace")
        assert process.returncode == 0, controller_output + output[-6000:].decode(
            errors="replace"
        )
        result = json.loads(evidence.read_text())
        assert result["attributes_restored"], (
            "terminal attributes were not restored exactly"
        )
        return output.decode(errors="replace"), result
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        selector.close()
        os.close(master)
        os.close(slave)


def _wizard(scenario: str, ready: int, config: Path):
    from textual.app import App
    from textual.widgets import Static

    from yoke_cli.config import onboard_clipboard
    from yoke_cli.config.onboard_terminal_driver import run_wizard_app
    from yoke_cli.config.onboard_wizard import WizardRunResult
    from yoke_cli.config.onboard_wizard_copy_open import CopyOpenFlow
    from yoke_cli.config.onboard_wizard_state import CopyTarget

    class TerminalApp(CopyOpenFlow, App):
        def compose(self):
            yield Static("isolated setup")

        def _note(self, text):
            config.with_suffix(".handoff").write_text(text)

        def _render_footer(self):
            pass

        def on_mount(self):
            os.write(ready, b"ready")
            if scenario in {"copy", "copy-loss"}:
                onboard_clipboard.remote_session = lambda: True
                self._set_copy_targets([CopyTarget("approval code", "DEMO-CODE")])
                self.call_later(self.copy_and_finish)
            elif scenario == "suspend":
                self.call_later(self.suspend_and_finish)
            elif scenario in {"foreground", "cancel"}:
                self.set_timer(0.15, self.exit)

        def copy_and_finish(self):
            self.action_copy_target()
            self.exit()

        @contextmanager
        def suspend(self):
            with super().suspend():
                if scenario == "copy-loss":
                    os.write(ready, b"copy")
                yield

        def suspend_and_finish(self):
            # The real Textual SIGTSTP/SIGCONT lifecycle is driven by controller.
            os.kill(os.getpid(), signal.SIGTSTP)
            self.set_timer(0.15, self.exit)

    run_wizard_app(TerminalApp())
    return WizardRunResult(
        cancelled=scenario == "cancel", exit_code=130 if scenario == "cancel" else 0
    )


def _worker(scenario: str, ready: int, config: Path) -> int:
    from yoke_cli.commands.adapters import onboard_interactive as adapter

    adapter.onboard_machine_setup.prepare = lambda *_: config.write_text("prepared")
    adapter.finish_pending_source_install = lambda *_: None
    adapter.onboard_wizard.run_wizard = lambda *_a, **_k: _wizard(
        scenario, ready, config
    )
    parsed = SimpleNamespace(
        config_path=str(config),
        api_url=None,
        token=None,
        token_file=None,
        quick=False,
        advanced=False,
        project_mode=None,
        project_checkout=None,
        apply=False,
        harness_posture=True,
        post_install=False,
    )
    job_signals = (signal.SIGTTIN, signal.SIGTTOU)
    handlers = [signal.getsignal(sig) for sig in job_signals]
    mask = signal.pthread_sigmask(signal.SIG_BLOCK, [])
    result = adapter.run_wizard(
        parsed,
        "",
        "quick",
        None,
        apply_with_report=lambda *_a, **_k: {},
        print_failure=lambda _: None,
    )
    assert [signal.getsignal(sig) for sig in job_signals] == handlers
    assert signal.pthread_sigmask(signal.SIG_BLOCK, []) == mask
    return result


def _controller(slave: int, scenario: str, evidence: Path) -> None:
    import fcntl
    import termios

    os.setsid()
    fcntl.ioctl(slave, termios.TIOCSCTTY, 0)
    before = termios.tcgetattr(slave)
    ready_read, ready_write = os.pipe()
    start_read, start_write = os.pipe()
    config = evidence.with_suffix(".config")
    worker = os.fork()
    if worker == 0:
        os.close(ready_read)
        os.close(start_write)
        os.setpgid(0, 0)
        for fd in (0, 1, 2):
            os.dup2(slave, fd)
        os.read(start_read, 1)
        import faulthandler

        faulthandler.dump_traceback_later(16)
        try:
            rc = _worker(scenario, ready_write, config)
        except BaseException:
            import traceback

            traceback.print_exc()
            rc = 99
        faulthandler.cancel_dump_traceback_later()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(rc)
    os.close(ready_write)
    os.close(start_read)
    os.setpgid(worker, worker)
    previous = signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGTTOU})
    status = None
    stops = []

    def terminate(*_):
        raise SystemExit(1)

    signal.signal(signal.SIGTERM, terminate)
    try:
        os.tcsetpgrp(slave, os.getpgrp() if scenario == "background" else worker)
        os.write(start_write, b"x")
        if scenario in {"loss", "loss-read", "copy-loss"}:
            readiness = selectors.DefaultSelector()
            readiness.register(ready_read, selectors.EVENT_READ)
            assert readiness.select(8), "wizard did not reach mount"
            assert os.read(ready_read, 5) == b"ready"
            if scenario == "copy-loss":
                assert readiness.select(8), "wizard did not reach copy suspension"
                assert os.read(ready_read, 4) == b"copy"
            readiness.close()
            os.tcsetpgrp(slave, os.getpgrp())
            if scenario == "loss-read":
                os.kill(worker, signal.SIGTTIN)
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            pid, observed = os.waitpid(worker, os.WNOHANG | os.WUNTRACED)
            if pid:
                if os.WIFSTOPPED(observed):
                    attrs = termios.tcgetattr(slave)
                    stops.append(
                        bool(attrs[3] & termios.ICANON and attrs[3] & termios.ECHO)
                    )
                    if scenario != "suspend":
                        raise AssertionError(
                            f"unexpected process stop: {os.WSTOPSIG(observed)}"
                        )
                    os.tcsetpgrp(slave, worker)
                    os.kill(worker, signal.SIGCONT)
                else:
                    status = observed
                    break
            time.sleep(0.01)
        assert status is not None, "worker timed out"
        evidence.write_text(
            json.dumps(
                {
                    "attributes_restored": termios.tcgetattr(slave) == before,
                    "exit_code": os.waitstatus_to_exitcode(status),
                    "prepared": config.exists(),
                    "stops_restored": stops,
                    "handoff": config.with_suffix(".handoff").read_text()
                    if config.with_suffix(".handoff").exists()
                    else None,
                }
            )
        )
    finally:
        if status is None:
            os.kill(worker, signal.SIGKILL)
            os.waitpid(worker, 0)
        signal.pthread_sigmask(signal.SIG_SETMASK, previous)
        for fd in (ready_read, start_write):
            os.close(fd)


if __name__ == "__main__":
    _controller(int(sys.argv[1]), sys.argv[2], Path(sys.argv[3]))
