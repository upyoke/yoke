"""Refuse host-side self-host operations outside the Linux/WSL path."""

from __future__ import annotations

import sys

from yoke_cli.config.install_advice import install_command
from yoke_contracts.refusal_recovery import compose_refusal


class NativeWindowsError(ValueError):
    """Native Windows cannot own a self-host server bundle."""

    code = "self_host_native_windows_requires_wsl2"
    def __init__(self) -> None:
        self.detail_lines = (
            "In Windows PowerShell, run `wsl --install -d Ubuntu` to install WSL2 and Ubuntu.",
            "Open Ubuntu and install Yoke inside that distribution: "
            f"`{install_command()}`.",
            "Make Docker Engine with Compose available inside Ubuntu, then rerun "
            "the self-host command or `yoke setup` there.",
        )
        super().__init__(compose_refusal(
            f"{self.code}: hosting a Yoke server on native Windows requires WSL2",
            recovery=" ".join(self.detail_lines),
        ))


def refuse() -> None:
    """Stop before host files, configuration, Docker or credentials are touched."""
    if sys.platform == "win32":
        raise NativeWindowsError()
