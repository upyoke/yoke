"""Close the browsers Yoke started before uninstall deletes their executables.

Identity browsers (``yoke browser open``) and Browser QA daemons run the
Chromium under the machine home's browser cache. Windows refuses to delete a
running executable, so uninstall closes them before it changes anything, and
stops when one stays open.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import suppress
import os
from pathlib import Path

import psutil

from yoke_cli.config.machine_uninstall_inventory import UninstallError
from yoke_contracts import platform_process
from yoke_contracts.playwright_cache import (
    YOKE_BROWSER_CACHE_PROJECT,
    resolve_playwright_cache,
)

CLOSE_SECONDS = 10


def stop(emit: Callable[[str], None]) -> None:
    try:
        from yoke_harness import browser_client, browser_runtime_home
        from yoke_harness import identity_browser_devtools as devtools
    except ImportError:
        browser_client = None

    if browser_client is not None:
        for port in devtools.live_ports():
            devtools.close(port)
        states = browser_runtime_home.runtime_dir() / "daemons"
        for path in sorted(states.glob("*/.daemon-state.json")):
            state = browser_client.DaemonState.load(path)
            if state is None or not browser_client.daemon_running(state):
                continue
            with suppress(RuntimeError):
                browser_client.daemon_stop(profile_dir=state.profile_dir)
            if browser_client.daemon_running(state):
                raise UninstallError(
                    f"uninstall_browser_running: Browser QA daemon PID {state.pid} "
                    "did not stop. Run `yoke qa browser status`, end that process, "
                    "then retry `yoke uninstall`; nothing else was changed."
                )
            emit(f"browsers: stopped Browser QA daemon (PID {state.pid})")

    cache = resolve_playwright_cache(YOKE_BROWSER_CACHE_PROJECT, None)
    assert cache is not None
    cache_root = Path(os.path.normcase(os.path.realpath(cache)))
    current_pid = os.getpid()
    protected = {current_pid, *(parent.pid for parent in platform_process.ancestors(current_pid))}
    matches = {}
    for process in psutil.process_iter():
        if process.pid in protected:
            continue
        try:
            executable = process.exe()
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            continue
        if executable:
            path = Path(os.path.normcase(os.path.realpath(executable)))
            if cache_root in path.parents:
                matches[process] = Path(executable).name

    alive = list(matches)
    # Wait both for the graceful close and for the kernel to finish killing.
    for force in (False, True):
        if force:
            for process in alive:
                with suppress(psutil.NoSuchProcess, psutil.AccessDenied):
                    process.kill()
        try:
            _, alive = psutil.wait_procs(alive, timeout=CLOSE_SECONDS)
        except psutil.AccessDenied:
            # A process can expose its executable without granting wait access.
            alive = [process for process in alive if process.is_running()]

    survivors = set(alive)
    for process in sorted(matches, key=lambda process: process.pid):
        if process not in survivors:
            emit(f"browsers: stopped {matches[process]} (PID {process.pid})")
    if survivors:
        names = ", ".join(
            f"{matches[process]} (PID {process.pid})"
            for process in sorted(survivors, key=lambda process: process.pid)
        )
        raise UninstallError(
            f"uninstall_browser_running: could not stop {names}. End the listed "
            "processes as their owner, then retry `yoke uninstall`; nothing else "
            "was changed."
        )
