"""Live memory and swap headroom required before a machine starts a native."""

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys

from yoke_contracts.machine_config.machine_capacity import (
    MEMORY_PER_LANE_BYTES,
    free_memory_bytes,
)

MIN_NATIVE_FREE_MEMORY_BYTES = 2 * MEMORY_PER_LANE_BYTES
MIN_NATIVE_SWAP_FREE_BYTES = MEMORY_PER_LANE_BYTES
NATIVE_SPAWN_STAGGER_SECONDS = 3


@dataclass(frozen=True)
class NativeCapacity:
    free_memory_bytes: int | None
    swap_total_bytes: int | None
    swap_free_bytes: int | None

    def refusal(self) -> str | None:
        if (
            self.free_memory_bytes is None
            or self.swap_total_bytes is None
            or self.swap_free_bytes is None
        ):
            return "native_capacity_unreadable"
        if (
            self.free_memory_bytes < 0
            or self.swap_total_bytes < 0
            or not 0 <= self.swap_free_bytes <= self.swap_total_bytes
        ):
            return "native_capacity_unreadable"
        if self.free_memory_bytes < MIN_NATIVE_FREE_MEMORY_BYTES:
            return "native_memory_headroom_low"
        if (
            self.swap_total_bytes > 0
            and self.swap_free_bytes < MIN_NATIVE_SWAP_FREE_BYTES
        ):
            return "native_swap_headroom_low"
        return None


def swap_headroom() -> tuple[int | None, int | None]:
    if sys.platform == "darwin":
        try:
            result = subprocess.run(
                ["sysctl", "-n", "vm.swapusage"],
                capture_output=True,
                text=True,
                timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None, None
        if result.returncode:
            return None, None
        found = {}
        for key, number, unit in re.findall(
            r"(total|free)\s*=\s*([\d.]+)([KMGT])", result.stdout
        ):
            found[key] = int(float(number) * 1024 ** ("KMGT".index(unit) + 1))
        return found.get("total"), found.get("free")
    if sys.platform.startswith("linux"):
        try:
            fields = {}
            for line in Path("/proc/meminfo").read_text().splitlines():
                key, _, value = line.partition(":")
                if key in {"SwapTotal", "SwapFree"}:
                    fields[key] = int(value.split()[0]) * 1024
            return fields.get("SwapTotal"), fields.get("SwapFree")
        except (OSError, ValueError, IndexError):
            return None, None
    return None, None


def observe_native_capacity() -> NativeCapacity:
    total, free = swap_headroom()
    return NativeCapacity(free_memory_bytes(), total, free)
