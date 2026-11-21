"""Runtime interface for pack prerequisites."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class PackPrerequisites(Protocol):
    collect_installed_pack_prerequisites: Callable[..., Any]
    unsatisfied_prerequisites: Callable[..., Any]


def get_pack_prerequisites() -> PackPrerequisites:
    return cast(PackPrerequisites, load_port("pack_prerequisites", PackPrerequisites))
