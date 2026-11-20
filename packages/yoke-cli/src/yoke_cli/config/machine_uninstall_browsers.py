"""Close the browsers Yoke started before uninstall deletes their executables.

Identity browsers (``yoke browser open``) and Browser QA daemons run the
Chromium under the machine home's browser cache. Windows refuses to delete a
running executable, so uninstall closes them before it changes anything, and
stops when one stays open.
"""

from __future__ import annotations

from collections.abc import Callable
import time

from yoke_cli.config.machine_uninstall_inventory import UninstallError

CLOSE_SECONDS = 10


def stop(emit: Callable[[str], None]) -> None:
    try:
        from yoke_harness import browser_client, browser_runtime_home
        from yoke_harness import identity_browser_devtools as devtools
    except ImportError:
        return  # No browser runtime in this install, so no Yoke browser runs.
    identity_ports = devtools.live_ports()
    for port in identity_ports:
        devtools.close(port)
    daemons = 0
    states = browser_runtime_home.runtime_dir() / "daemons"
    for path in sorted(states.glob("*/.daemon-state.json")):
        state = browser_client.DaemonState.load(path)
        if state is not None and browser_client.daemon_running(state):
            try:
                browser_client.daemon_stop(profile_dir=state.profile_dir)
            except RuntimeError:
                pass  # It exited between the check and the stop.
            if browser_client.daemon_running(state):
                raise UninstallError(
                    f"uninstall_browser_running: Browser QA daemon PID {state.pid} "
                    "did not stop. Run `yoke qa browser status`, end that process, "
                    "then retry `yoke uninstall`; nothing else was changed."
                )
            daemons += 1
    deadline = time.monotonic() + CLOSE_SECONDS
    while (open_ports := set(devtools.live_ports()) & set(identity_ports)):
        if time.monotonic() >= deadline:
            raise UninstallError(
                "uninstall_browser_running: the identity browser on DevTools port "
                f"{', '.join(map(str, sorted(open_ports)))} did not close within "
                f"{CLOSE_SECONDS} seconds. Close its window, then retry "
                "`yoke uninstall`; nothing else was changed."
            )
        time.sleep(0.2)
    if identity_ports or daemons:
        emit(
            f"browsers: closed {len(identity_ports)} identity browser(s) and "
            f"{daemons} Browser QA daemon(s)"
        )

