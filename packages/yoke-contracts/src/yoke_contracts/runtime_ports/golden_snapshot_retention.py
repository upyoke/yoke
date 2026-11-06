"""Runtime interface for golden snapshot retention."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class GoldenSnapshotRetention(Protocol):
    """Operations and values supplied by the executing adapter."""

    SnapshotRetentionError: type[Any]
    retain_after_verified_capture: Callable[..., Any]
    retention_summary: Callable[..., Any]


def get_golden_snapshot_retention() -> GoldenSnapshotRetention:
    return cast(GoldenSnapshotRetention, load_port("golden_snapshot_retention", GoldenSnapshotRetention))
