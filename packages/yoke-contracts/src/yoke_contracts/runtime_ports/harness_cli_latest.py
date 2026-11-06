"""Runtime interface for harness cli latest."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class HarnessCliLatest(Protocol):
    """Operations and values supplied by the executing adapter."""

    LatestReleaseUnavailable: type[Any]
    fetch_release_channel: Callable[..., Any]
    latest_harness_cli_versions: Callable[..., Any]
    warn_capture_behind_latest: Callable[..., Any]


def get_harness_cli_latest() -> HarnessCliLatest:
    return cast(HarnessCliLatest, load_port("harness_cli_latest", HarnessCliLatest))
