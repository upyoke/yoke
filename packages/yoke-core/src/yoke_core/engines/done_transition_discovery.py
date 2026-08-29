"""Discovery scan helpers for done-transition.

The scan addresses the item by its public ``PREFIX-N`` ref. A Python
``int`` is ``items.id``; a digit *string* is a project-local public
sequence, so stringifying the internal id here made the scan re-resolve a
different row — or, far more often, none at all.
"""

from __future__ import annotations

import io
import sys
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class DiscoveryScanResult:
    """Outcome of the done-transition discovery scan."""

    returncode: int
    step_marker: str  # "9" or "9-degraded"
    message: str

    @property
    def is_degraded(self) -> bool:
        return self.step_marker == "9-degraded"


def _load_discovery_metadata(path: Path) -> int:
    """Read discovery metadata emitted by discovery_scan."""
    unreviewed = 0
    try:
        for line in path.read_text().splitlines():
            if line.startswith("UNREVIEWED_OUROBOROS="):
                unreviewed = int(line.split("=", 1)[1].strip() or "0")
    except (OSError, ValueError):
        return 0
    return unreviewed


def _apply_discovery_scan(public_ref: str, result) -> DiscoveryScanResult:
    """Run the discovery scan for *public_ref*, mirror output, record the step.

    Records ``"9"`` on a clean scan and ``"9-degraded"`` with a structured
    ``discovery_scan_degraded`` warning when the scan refuses, so a scan
    that never ran stops being indistinguishable from one that found
    nothing.
    """
    from yoke_core.domain import discovery_scan as _discovery_scan

    buf = io.StringIO()
    err = io.StringIO()
    rc = _discovery_scan.run_scan(public_ref, stdout=buf, stderr=err)
    disc_output = buf.getvalue()
    if disc_output:
        print(disc_output, end="" if disc_output.endswith("\n") else "\n")
    scan_error = err.getvalue()
    if scan_error:
        print(scan_error, end="" if scan_error.endswith("\n") else "\n",
              file=sys.stderr)
    for line in disc_output.splitlines():
        if line.startswith("DISCOVERY_FILE="):
            disc_file = line.split("=", 1)[1].strip()
            if disc_file and Path(disc_file).exists():
                result.discovery_unreviewed = _load_discovery_metadata(Path(disc_file))
            break

    if rc == 0:
        outcome = DiscoveryScanResult(returncode=0, step_marker="9", message="ok")
        result.add_step(outcome.step_marker)
        return outcome

    message = (
        f"discovery scan returned {rc} for {public_ref} — unreviewed "
        f"ouroboros entries were not surfaced: {scan_error.strip() or 'no detail'}. "
        "Review them with /yoke curate."
    )
    print(f"Warning: {message}", file=sys.stderr)
    outcome = DiscoveryScanResult(
        returncode=rc, step_marker="9-degraded", message=message
    )
    result.add_step(outcome.step_marker)
    result.warnings.append({
        "code": "discovery_scan_degraded",
        "step": "9",
        "message": message,
    })
    return outcome


__all__ = ["DiscoveryScanResult", "_apply_discovery_scan"]
