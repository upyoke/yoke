"""Runtime interface for python venv dependencies."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class PythonVenvDependencies(Protocol):
    ensure_venv_support: Callable[..., Any]


def get_python_venv_dependencies() -> PythonVenvDependencies:
    return cast(PythonVenvDependencies, load_port("python_venv_dependencies", PythonVenvDependencies))
