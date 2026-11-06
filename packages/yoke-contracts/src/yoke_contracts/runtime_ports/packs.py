"""Runtime interface for packs."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class Packs(Protocol):
    """Operations and values supplied by the executing adapter."""

    PackClientError: Any
    run_pack_operation: Any
    run_pack_relink: Any


def get_packs() -> Packs:
    return cast(Packs, load_port("packs", Packs))
