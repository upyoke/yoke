"""Subprocess boundary for the local-core launcher."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Mapping, Protocol, Sequence


@dataclass(frozen=True)
class CommandResult:
    args: tuple[str, ...]
    returncode: int
    stdout: str = ""
    stderr: str = ""


class CommandRunner(Protocol):
    def run(
        self,
        args: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: int = 30,
    ) -> CommandResult:
        ...


class SubprocessRunner:
    """Run external container tools without exposing them to tests."""

    def run(
        self,
        args: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: int = 30,
    ) -> CommandResult:
        cmd = tuple(str(part) for part in args)
        try:
            completed = subprocess.run(
                list(cmd),
                env=dict(env) if env is not None else None,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError as exc:
            return CommandResult(cmd, 127, "", str(exc))
        except subprocess.TimeoutExpired as exc:
            return CommandResult(
                cmd,
                124,
                exc.stdout or "",
                exc.stderr or f"timed out after {timeout}s",
            )
        return CommandResult(
            cmd, completed.returncode, completed.stdout, completed.stderr,
        )


__all__ = ["CommandResult", "CommandRunner", "SubprocessRunner"]
