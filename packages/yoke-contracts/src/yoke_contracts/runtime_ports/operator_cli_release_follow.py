"""Runtime interface for operator cli release follow."""

from __future__ import annotations

from typing import Any, Protocol, cast

from yoke_contracts.runtime_ports.loader import load_port


class OperatorCliReleaseFollow(Protocol):
    """Operations and values supplied by the executing adapter."""

    refresh_skip_lines: Any


def get_operator_cli_release_follow() -> OperatorCliReleaseFollow:
    return cast(OperatorCliReleaseFollow, load_port("operator_cli_release_follow", OperatorCliReleaseFollow))
