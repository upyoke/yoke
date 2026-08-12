"""In-memory host adapter for Machine QA fixture runner tests."""

from __future__ import annotations

import shlex
from types import SimpleNamespace
from typing import Callable

from yoke_contracts.machine_qa_execution import HOST_TEST_COMMAND
from yoke_core.domain.machine_qa_fixture_operations import (
    MachineQaFixtureOperationRunner,
)


class FakeRemote:
    """Record remote actions while modeling the bounded fixture filesystem."""

    def __init__(self) -> None:
        self.commands: list[tuple[str, int]] = []
        self.uploads: dict[str, str] = {}
        self.existing: set[str] = set()
        self.directories: set[str] = set()
        self.contents: dict[str, str] = {}
        self.terminal_sizes: list[tuple[int, int]] = []
        self.fail_once_contains: str | None = None
        self.stdout = "remote-token-value"
        self.on_successful_command: Callable[[str], None] | None = None

    def run(self, command: str, *, timeout: int = 60):
        self.commands.append((command, timeout))
        if self.fail_once_contains is not None and self.fail_once_contains in command:
            self.fail_once_contains = None
            return SimpleNamespace(
                returncode=1,
                stdout=self.stdout,
                stderr=self.stdout,
            )
        argv = shlex.split(command)
        returncode = 0
        if argv[:2] == [HOST_TEST_COMMAND, "-f"]:
            returncode = 0 if argv[2] in self.existing else 1
        elif argv[:2] == [HOST_TEST_COMMAND, "-d"]:
            returncode = 0 if argv[2] in self.directories else 1
        elif argv[:3] == ["/bin/rm", "-rf", "--"]:
            for path in argv[3:]:
                self._remove(path)
        elif argv[:2] == ["/bin/mkdir", "-p"]:
            self.directories.update(argv[2:])
        elif argv and argv[0] == "/bin/cp":
            self._copy(argv[-2], argv[-1])
        if returncode == 0 and self.on_successful_command is not None:
            self.on_successful_command(command)
        return SimpleNamespace(
            returncode=returncode,
            stdout=self.stdout,
            stderr=self.stdout,
        )

    def upload(self, path: str, content: str) -> None:
        self.uploads[path] = content
        self.existing.add(path)
        self.contents[path] = content

    def _remove(self, path: str) -> None:
        prefix = path.rstrip("/") + "/"
        self.existing = {
            item
            for item in self.existing
            if item != path and not item.startswith(prefix)
        }
        self.directories = {
            item
            for item in self.directories
            if item != path and not item.startswith(prefix)
        }
        self.contents = {
            item: content
            for item, content in self.contents.items()
            if item != path and not item.startswith(prefix)
        }

    def _copy(self, source: str, target: str) -> None:
        if source in self.directories:
            self.directories.add(target)
            prefix = source.rstrip("/") + "/"
            for directory in tuple(self.directories):
                if directory.startswith(prefix):
                    self.directories.add(target + directory[len(source) :])
            for path in tuple(self.existing):
                if path.startswith(prefix):
                    copied = target + path[len(source) :]
                    self.existing.add(copied)
                    if path in self.contents:
                        self.contents[copied] = self.contents[path]
            return
        self.existing.add(target)
        if source in self.contents:
            self.contents[target] = self.contents[source]


def fixture_runner(remote: FakeRemote) -> MachineQaFixtureOperationRunner:
    """Create a runner against the deterministic in-memory adapter."""
    return MachineQaFixtureOperationRunner(
        run_remote=remote.run,
        upload_text=remote.upload,
        home="/Users/tester",
        prepare_terminal_size=lambda columns, rows: remote.terminal_sizes.append(
            (columns, rows)
        ),
    )


def operation(operation_id: str, **parameters: object) -> dict[str, object]:
    """Build one registered fixture-operation request."""
    return {"id": operation_id, "parameters": parameters}


__all__ = ["FakeRemote", "fixture_runner", "operation"]
