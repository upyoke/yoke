"""Hold the import container alive until its private exec bridge has returned."""

from __future__ import annotations

import os
import pwd
import signal
import subprocess
import sys
import threading

from yoke_contracts.self_host_bootstrap import (
    IMPORT_UNIVERSE_ARG,
    RECOVER_IMPORT_CREDENTIAL_ARG,
)
from yoke_contracts.self_host_handoff import HANDOFF_TIMEOUT_SECONDS
from yoke_core.tools.self_host_server_bootstrap import (
    SELF_HOST_RUNTIME_USER,
    assert_no_effective_linux_capabilities,
    drop_to_self_host_runtime_identity,
)


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args not in ([IMPORT_UNIVERSE_ARG], [RECOVER_IMPORT_CREDENTIAL_ARG]):
        print(
            "self_host_import_supervisor_arguments_invalid: use self-host import",
            file=sys.stderr,
        )
        return 2
    finished = threading.Event()
    previous = signal.signal(signal.SIGUSR1, lambda *_args: finished.set())
    child = None
    try:
        child = subprocess.Popen(
            [sys.executable, "-m", "yoke_core.tools.self_host_server_bootstrap", *args]
        )
        if os.geteuid() == 0:
            account = pwd.getpwnam(SELF_HOST_RUNTIME_USER)
            drop_to_self_host_runtime_identity(uid=account.pw_uid, gid=account.pw_gid)
            assert_no_effective_linux_capabilities()
        result = child.wait()
        if not finished.wait(HANDOFF_TIMEOUT_SECONDS):
            print(
                "self_host_import_bridge_unconfirmed: the host did not finish its "
                "private bridge; inspect the host import failure and retry import",
                file=sys.stderr,
            )
            return 1
        return result if result >= 0 else 128 - result
    except (OSError, RuntimeError, KeyError):
        print(
            "self_host_import_supervisor_failed: inspect container logs, repair "
            "the runtime identity or process failure, and retry self-host import",
            file=sys.stderr,
        )
        return 1
    finally:
        signal.signal(signal.SIGUSR1, previous)
        if child is not None and child.poll() is None:
            child.kill()
            child.wait()


if __name__ == "__main__":
    raise SystemExit(main())
