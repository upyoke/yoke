"""Discovery scan helpers for done-transition."""

from __future__ import annotations

import io
import sys
from pathlib import Path

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


def _apply_discovery_scan(item_id: int, result) -> None:
    """Run the Python discovery scan in-process, mirror its output, and
    capture its metadata file."""
    from yoke_core.domain import discovery_scan as _discovery_scan

    buf = io.StringIO()
    _discovery_scan.run_scan(str(item_id), stdout=buf, stderr=sys.stderr)
    disc_output = buf.getvalue()
    if disc_output:
        print(disc_output, end="" if disc_output.endswith("\n") else "\n")
    for line in disc_output.splitlines():
        if line.startswith("DISCOVERY_FILE="):
            disc_file = line.split("=", 1)[1].strip()
            if disc_file and Path(disc_file).exists():
                result.discovery_unreviewed = _load_discovery_metadata(Path(disc_file))
            break
