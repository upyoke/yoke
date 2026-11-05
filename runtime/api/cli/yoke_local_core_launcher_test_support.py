# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from pathlib import Path

from typing import Mapping, Sequence

from yoke_cli import main as yoke_cli_main

from yoke_cli import operation_inventory as op_inventory

from yoke_cli import product_boundary_inventory as boundary_inventory

from yoke_cli.local_core.launcher import LocalCoreLauncher

from yoke_cli.local_core.checkout_build import identity

from yoke_cli.local_core.runner import CommandResult

TOKEN = "yoke-test-token"


class FakeRunner:
    def __init__(self, *, docker_rc: int = 0) -> None:
        self.docker_rc = docker_rc
        self.calls: list[tuple[str, ...]] = []

    def run(
        self,
        args: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: int = 30,
    ) -> CommandResult:
        cmd = tuple(str(part) for part in args)
        self.calls.append(cmd)
        if cmd[:3] == ("docker", "version", "--format"):
            if self.docker_rc == 127:
                return CommandResult(cmd, 127, "", "docker missing")
            return CommandResult(cmd, self.docker_rc, "26.0.0\n", "")
        if cmd[:2] == ("docker", "inspect"):
            if self.docker_rc != 0:
                return CommandResult(cmd, self.docker_rc, "", "docker missing")
            return CommandResult(cmd, 0, "true healthy\n", "")
        if "yoke_core.domain.api_tokens_cli" in cmd:
            return CommandResult(cmd, 0, json.dumps({"raw_token": TOKEN}), "")
        return CommandResult(cmd, 0, "", "")
