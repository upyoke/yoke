"""Shared run/error-handling plumbing for machine-config writer adapters.

Split out from :mod:`yoke_cli.commands.adapters.config_write` so sibling
adapter modules (e.g. :mod:`config_write_project`) reuse the same shape
without an import cycle back into that module.
"""

from __future__ import annotations

from yoke_cli.transport.human_values import write_local
import sys
from typing import Callable

from yoke_contracts.machine_config import reader as machine_config
from yoke_cli.config import writer


def run(operation: "Callable[[], dict]") -> int:
    try:
        result = operation()
    except machine_config_errors() as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    write_local(result, sys.stdout)
    return 0


def machine_config_errors() -> tuple[type[Exception], ...]:
    return (writer.MachineConfigWriteError, machine_config.MachineConfigError)


__all__ = ["machine_config_errors", "run"]
