"""Runtime interface for golden harness clis."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class GoldenHarnessClis(Protocol):
    """Operations and values supplied by the executing adapter."""

    install_harness_clis: Callable[..., Any]
    read_golden_harness_clis: Callable[..., Any]


def get_golden_harness_clis() -> GoldenHarnessClis:
    return cast(GoldenHarnessClis, load_port("golden_harness_clis", GoldenHarnessClis))
