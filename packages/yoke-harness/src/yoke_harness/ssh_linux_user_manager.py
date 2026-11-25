"""Prove a Linux test user's systemd user manager answers before reset or verify relies on it."""

from __future__ import annotations

import inspect
import json
import shlex
from typing import Sequence

from yoke_contracts.machine_qa_failures import (
    SSH_UNAVAILABLE,
    bounded_machine_qa_diagnostic,
)
from yoke_contracts.systemd_service import SERVICE_QUERY_TIMEOUT_SECONDS
from yoke_contracts.systemd_user_manager import (
    USER_MANAGER_PROBE,
    USER_MANAGER_UNAVAILABLE,
    user_manager_unavailable,
)
from yoke_contracts.test_machine_types import HostActionResult

# Runs on the host; the remote interpreter cannot import yoke_contracts.
_PROBE_PROGRAM = inspect.getsource(user_manager_unavailable) + (
    r"""
import os, pathlib, shutil, subprocess
def user_manager_missing():
    if not shutil.which("systemctl"): return None
    try:
        result = subprocess.run(__PROBE__, capture_output=True, text=True, timeout=__TIMEOUT__)
        if result.returncode == 0: return None
        stderr = result.stderr
    except subprocess.TimeoutExpired:
        stderr = " ".join(__PROBE__) + " did not answer within __TIMEOUT__s"
    distro = os.environ.get("WSL_DISTRO_NAME") or None
    try: release = pathlib.Path("/proc/sys/kernel/osrelease").read_text().lower()
    except OSError: release = ""
    return user_manager_unavailable(stderr, wsl=bool(distro) or "microsoft" in release, distro=distro)
""".replace("__PROBE__", repr(list(USER_MANAGER_PROBE))).replace(
        "__TIMEOUT__", str(SERVICE_QUERY_TIMEOUT_SECONDS)
    )
)

# The archive program runs this before reset stops, stashes or removes anything.
RESET_USER_MANAGER_PROGRAM = (
    _PROBE_PROGRAM
    + f"""
missing = user_manager_missing()
if missing: refuse({USER_MANAGER_UNAVAILABLE!r}, **missing)
"""
)

_VERIFY_PROGRAM = _PROBE_PROGRAM + "import json; print(json.dumps(user_manager_missing()))"


def check_linux_user_manager(run, *, secret_values: Sequence[str]) -> HostActionResult:
    """Fail verify with the reset's own code, stderr and recovery."""
    result = run(shlex.join(("/usr/bin/python3", "-c", _VERIFY_PROGRAM)), timeout=60)
    try:
        missing = json.loads(result.stdout) if result.returncode == 0 else False
    except ValueError:
        missing = False
    if missing is None:
        return HostActionResult(True, {"systemd_user_manager": "available"})
    if isinstance(missing, dict) and {"user_manager_stderr", "recovery"} <= missing.keys():
        return HostActionResult(
            False,
            {
                "systemd_user_manager": "unavailable",
                "user_manager_stderr": bounded_machine_qa_diagnostic(
                    missing["user_manager_stderr"], secret_values
                ),
                "recovery": missing["recovery"],
            },
            USER_MANAGER_UNAVAILABLE,
        )
    return HostActionResult(
        False,
        {
            "systemd_user_manager": "unreadable",
            "exit_code": result.returncode,
            "stdout": bounded_machine_qa_diagnostic(result.stdout, secret_values),
            "stderr": bounded_machine_qa_diagnostic(result.stderr, secret_values),
            "recovery": "Repair SSH and the host's Python 3 user-manager probe, then retry yoke test-machine verify.",
        },
        SSH_UNAVAILABLE
        if result.returncode in (124, 255)
        else "linux_user_manager_probe_failed",
    )
