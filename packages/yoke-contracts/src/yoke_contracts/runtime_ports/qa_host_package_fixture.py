"""Runtime interface for qa host package fixture."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class QaHostPackageFixture(Protocol):
    """Operations and values supplied by the executing adapter."""

    record_host_packages: Callable[..., Any]
    restore_host_packages: Callable[..., Any]


def get_qa_host_package_fixture() -> QaHostPackageFixture:
    return cast(QaHostPackageFixture, load_port("qa_host_package_fixture", QaHostPackageFixture))
