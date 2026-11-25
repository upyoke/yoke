"""Verify records a machine-wide QA fixture script prints, read on the controller.

Each fixture script ends with one marked JSON line describing the state it
left. The fixture library writes them on the host; the SYSTEM script runner
reads them back, so both sides share this one marker and parser.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.machine_qa_failures import HostControlLocalError

VERIFY_MARKER = "YOKE_MACHINE_FIXTURE_VERIFY "
FIXTURE_FAILED = "machine_fixture_failed"
RUNNER_UNAVAILABLE = "machine_fixture_runner_unavailable"


class MachineFixtureFailed(HostControlLocalError):
    """A SYSTEM fixture script failed; keeps every verify record it printed."""

    def __init__(self, *, records: list[dict[str, Any]], **kwargs: Any) -> None:
        super().__init__(code=FIXTURE_FAILED, phase="machine_fixture", **kwargs)
        self.records = records


def verify_records(stdout: str) -> list[dict[str, Any]]:
    """Return every well-formed verify record, in the order printed."""
    records = []
    for line in (stdout or "").splitlines():
        line = line.strip().lstrip("﻿")
        if not line.startswith(VERIFY_MARKER):
            continue
        try:
            record = json.loads(line[len(VERIFY_MARKER) :])
        except ValueError:
            continue
        if isinstance(record, dict) and isinstance(record.get("fixture"), str):
            records.append(record)
    return records


__all__ = [
    "FIXTURE_FAILED",
    "MachineFixtureFailed",
    "RUNNER_UNAVAILABLE",
    "VERIFY_MARKER",
    "verify_records",
]
