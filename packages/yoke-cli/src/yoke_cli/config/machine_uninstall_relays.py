"""Packaged lifecycle bridge for services whose connection was retired."""

from pathlib import Path
import subprocess
import sys

from yoke_cli.config.machine_uninstall_inventory import UninstallError
from yoke_contracts.self_host_bootstrap_output import redact_api_tokens


def remove_saved_services(home: Path) -> None:
    """Use the relay installer's service ownership, never rebuild an alias."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "yoke_core.tools.install_session_relay",
            "uninstall-owned",
            "--machine-home",
            str(home),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=300,
    )
    if result.returncode:
        detail = redact_api_tokens((result.stderr or result.stdout).strip())[-2048:]
        raise UninstallError(
            f"uninstall_saved_relays_failed: {detail}. "
            "Repair the named saved service and retry `yoke uninstall`; "
            "the machine home and CLI remain available."
        )
