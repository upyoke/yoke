"""CLI registry rows for ephemeral environment wrappers."""

from __future__ import annotations

from typing import Callable, Dict, List, Tuple

from yoke_cli.commands import flag_adapters as _adapters


AdapterFn = Callable[[List[str]], int]


EPHEMERAL_ENV_SUBCOMMAND_REGISTRY: Dict[Tuple[str, ...], Tuple[str, AdapterFn]] = {
    ("ephemeral-env", "create"):
        ("ephemeral_env.create", _adapters.ephemeral_env_create),
    ("ephemeral-env", "update"):
        ("ephemeral_env.update", _adapters.ephemeral_env_update),
}


__all__ = ["EPHEMERAL_ENV_SUBCOMMAND_REGISTRY"]
