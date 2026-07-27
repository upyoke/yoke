"""Shared transport double for dedicated Test Mac reset tests."""

from __future__ import annotations

import shlex
from types import SimpleNamespace

from yoke_core.domain.ssh_mac_full_reset_contract import FULL_RESET_REMOTE_PATH


class FakeResetTransport:
    def __init__(self, stdout: str, *, reset_returncode: int = 0) -> None:
        self.stdout = stdout
        self.reset_returncode = reset_returncode
        self.uploads: dict[str, str] = {}
        self.commands: list[tuple[str, int]] = []
        self.cleanup_returncode = 0

    def upload(self, path: str, content: str) -> None:
        self.uploads[path] = content

    def run(self, command: str, *, timeout: int = 60):
        self.commands.append((command, timeout))
        argv = shlex.split(command)
        if argv and argv[0] == FULL_RESET_REMOTE_PATH:
            return SimpleNamespace(
                returncode=self.reset_returncode,
                stdout=self.stdout,
            )
        if argv[:3] == ["/bin/rm", "-f", "--"]:
            return SimpleNamespace(
                returncode=self.cleanup_returncode,
                stdout="",
            )
        return SimpleNamespace(returncode=0, stdout="")


__all__ = ["FakeResetTransport"]
