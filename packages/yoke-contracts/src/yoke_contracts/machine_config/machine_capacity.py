"""What one machine can carry: memory, load, cores, and its worker-lane cap.

A relay publishes this reading with every heartbeat so the launch plane can
refuse to place a worker on a box that has no room for one. Each harness
worker costs roughly half a gigabyte resident, so the cap defaults to what
total memory leaves after a reserve for the operating system, the browser,
and the operator's own tools; ``max_worker_lanes`` in ``~/.yoke/config.json``
settings overrides that derivation on the machine it describes.

Values only ever leave the machine. The probe never raises: a platform it
cannot read reports ``None`` for that field and the control plane treats an
unknown as "no evidence of room", never as room.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import os
import re
import subprocess
import sys
from typing import Any, Mapping

MAX_WORKER_LANES_KEY = "max_worker_lanes"
RESERVED_MEMORY_BYTES = 12 * 1024**3
MEMORY_PER_LANE_BYTES = 512 * 1024**2
CAP_SOURCE_SETTING = MAX_WORKER_LANES_KEY
CAP_SOURCE_DERIVED = "derived_from_total_memory"
CAP_SOURCE_UNREADABLE = "total_memory_unreadable"
CAPACITY_KEYS = (
    "total_memory_bytes",
    "free_memory_bytes",
    "load_average_1m",
    "core_count",
    "max_worker_lanes",
    "cap_source",
    "observed_at",
)
_INT_KEYS = (
    "total_memory_bytes",
    "free_memory_bytes",
    "core_count",
    "max_worker_lanes",
)


@dataclass(frozen=True)
class MachineCapacityReading:
    total_memory_bytes: int | None
    free_memory_bytes: int | None
    load_average_1m: float | None
    core_count: int | None
    max_worker_lanes: int | None
    cap_source: str
    observed_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def free_memory_bytes() -> int | None:
    """Reclaimable free memory in bytes, or ``None`` when unknowable.

    macOS sums the free, inactive, speculative, and purgeable pages from
    ``vm_stat`` -- all reclaimable without disk I/O. Linux reads
    ``MemAvailable`` from ``/proc/meminfo``.
    """
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["vm_stat"], capture_output=True, text=True, timeout=2
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, TypeError):
            # TypeError surfaces when a test fixture monkeypatches
            # subprocess.run with a narrower signature; unknowable, not broken.
            return None
        if result.returncode != 0:
            return None
        page_size = 4096
        page_size_match = re.search(r"page size of (\d+) bytes", result.stdout)
        if page_size_match:
            page_size = int(page_size_match.group(1))
        pages = 0
        for key in (
            "Pages free",
            "Pages inactive",
            "Pages speculative",
            "Pages purgeable",
        ):
            match = re.search(rf"{re.escape(key)}:\s+(\d+)", result.stdout)
            if match:
                pages += int(match.group(1))
        return pages * page_size if pages else None
    if sys.platform.startswith("linux"):
        try:
            with open("/proc/meminfo", encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("MemAvailable:"):
                        parts = line.split()
                        if len(parts) >= 2 and parts[1].isdigit():
                            return int(parts[1]) * 1024
        except OSError:
            return None
    return None


def total_memory_bytes() -> int | None:
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
    except (AttributeError, OSError, ValueError):
        return None
    if pages <= 0 or page_size <= 0:
        return None
    return int(pages) * int(page_size)


def load_average_1m() -> float | None:
    try:
        return float(os.getloadavg()[0])
    except (AttributeError, OSError):
        return None


def core_count() -> int | None:
    return os.cpu_count()


def derived_lane_cap(total_memory: int | None) -> int | None:
    """Lanes total memory can carry after the reserve; one when only a sliver is left."""
    if total_memory is None:
        return None
    return max(1, (total_memory - RESERVED_MEMORY_BYTES) // MEMORY_PER_LANE_BYTES)


def configured_lane_cap(settings: Mapping[str, Any] | None) -> int | None:
    """The operator's ``max_worker_lanes`` when set to a positive integer."""
    raw = (settings or {}).get(MAX_WORKER_LANES_KEY)
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if value > 0 else None


def observe_machine_capacity(
    settings: Mapping[str, Any] | None,
    *,
    observed_at: str,
) -> MachineCapacityReading:
    """Read this machine's capacity, resolving the cap from settings or memory."""
    total = total_memory_bytes()
    configured = configured_lane_cap(settings)
    if configured is not None:
        cap, source = configured, CAP_SOURCE_SETTING
    else:
        cap = derived_lane_cap(total)
        source = CAP_SOURCE_DERIVED if cap is not None else CAP_SOURCE_UNREADABLE
    return MachineCapacityReading(
        total_memory_bytes=total,
        free_memory_bytes=free_memory_bytes(),
        load_average_1m=load_average_1m(),
        core_count=core_count(),
        max_worker_lanes=cap,
        cap_source=source,
        observed_at=observed_at,
    )


def sanitize_machine_capacity(raw: Any) -> dict[str, Any]:
    """Allowlisted, type-coerced reading; an unreadable document is empty."""
    if not isinstance(raw, Mapping):
        return {}
    cleaned: dict[str, Any] = {}
    for key in CAPACITY_KEYS:
        value = raw.get(key)
        if value is None or isinstance(value, bool):
            cleaned[key] = None
            continue
        try:
            if key in _INT_KEYS:
                number = int(value)
                cleaned[key] = number if number >= 0 else None
            elif key == "load_average_1m":
                number = float(value)
                cleaned[key] = number if number >= 0 else None
            else:
                cleaned[key] = str(value).strip()[:128] or None
        except (TypeError, ValueError):
            cleaned[key] = None
    return cleaned


def format_bytes(value: int | None) -> str:
    if value is None:
        return "unknown"
    units = ("B", "KB", "MB", "GB", "TB")
    size = float(value)
    index = 0
    while size >= 1024 and index < len(units) - 1:
        size /= 1024
        index += 1
    precision = 0 if index < 3 else 1
    return f"{size:.{precision}f} {units[index]}"


__all__ = [
    "CAPACITY_KEYS",
    "CAP_SOURCE_DERIVED",
    "CAP_SOURCE_SETTING",
    "CAP_SOURCE_UNREADABLE",
    "MAX_WORKER_LANES_KEY",
    "MEMORY_PER_LANE_BYTES",
    "MachineCapacityReading",
    "RESERVED_MEMORY_BYTES",
    "configured_lane_cap",
    "core_count",
    "derived_lane_cap",
    "format_bytes",
    "free_memory_bytes",
    "load_average_1m",
    "observe_machine_capacity",
    "sanitize_machine_capacity",
    "total_memory_bytes",
]
