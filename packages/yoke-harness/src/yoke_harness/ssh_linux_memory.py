"""Read Linux host RAM before verification can restore any baseline."""

from __future__ import annotations

import shlex
from typing import Sequence

from yoke_contracts.machine_config.native_capacity import (
    MIN_TEST_MACHINE_USABLE_MEMORY_BYTES,
)
from yoke_contracts.machine_qa_failures import (
    SSH_UNAVAILABLE,
    bounded_machine_qa_diagnostic,
)
from yoke_harness.test_machine_types import HostActionResult


_MEMORY_PROGRAM = (
    "import os; print(os.sysconf('SC_PHYS_PAGES') * os.sysconf('SC_PAGE_SIZE'))"
)


def check_linux_memory(run, *, secret_values: Sequence[str]) -> HostActionResult:
    """Use the existing physical-page probe and native-capacity floor owner."""
    result = run(shlex.join(("/usr/bin/python3", "-c", _MEMORY_PROGRAM)), timeout=20)
    try:
        observed = int(result.stdout.strip()) if result.returncode == 0 else None
    except ValueError:
        observed = None
    evidence = {
        "total_memory_bytes": observed,
        "required_total_memory_bytes": MIN_TEST_MACHINE_USABLE_MEMORY_BYTES,
    }
    if observed is None or observed <= 0:
        return HostActionResult(
            False,
            {
                **evidence,
                "exit_code": result.returncode,
                "stdout": bounded_machine_qa_diagnostic(result.stdout, secret_values),
                "stderr": bounded_machine_qa_diagnostic(result.stderr, secret_values),
                "recovery": "Repair SSH and the host's Python 3 physical-memory probe, then retry yoke test-machine verify.",
            },
            SSH_UNAVAILABLE
            if result.returncode in (124, 255)
            else "test_machine_memory_unreadable",
        )
    if observed < MIN_TEST_MACHINE_USABLE_MEMORY_BYTES:
        return HostActionResult(
            False,
            {
                **evidence,
                "recovery": (
                    f"This Linux host reports {observed} total RAM bytes; "
                    f"at least {MIN_TEST_MACHINE_USABLE_MEMORY_BYTES} bytes "
                    "of usable RAM are required. Resize to a 4 GiB instance "
                    "(8 GiB recommended; kernel reservations reduce usable RAM), "
                    "provision at least 2 GiB swap, then retry yoke test-machine verify."
                ),
            },
            "test_machine_memory_below_minimum",
        )
    return HostActionResult(True, evidence)
