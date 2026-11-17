"""Expand ``~`` in parsed Bash mutation targets against the client's home.

Path-claim target resolution canonicalizes paths lexically. A leading ``~``
left for it would expand to the home of whichever machine evaluates the
chain, so the guard expands it first from the client's home fact
(:data:`yoke_contracts.hook_runner.session_cwd.CLIENT_MACHINE_HOME_KEY`).
"""

from __future__ import annotations

from dataclasses import replace
from yoke_contracts.hook_runner.bash_paths import is_absolute, resolve_bash_path
from typing import Any, List

from yoke_contracts.hook_runner.session_cwd import client_machine_home
from yoke_core.domain.path_claim_bash_parser import Mutation


def expand_client_home(mutations: List[Mutation], payload: Any) -> List[Mutation]:
    """Return *mutations* with ``~`` / ``~/...`` targets under the client home."""
    home = client_machine_home(payload) if isinstance(payload, dict) else ""
    out = []
    for mut in mutations:
        target = mut.target_path
        if mut.verb not in {"ambiguous", "suppressed"} and (
            is_absolute(target) or (home and target.startswith("~"))
        ):
            target = resolve_bash_path(target, home=home)
        out.append(replace(mut, target_path=target))
    return out


__all__ = ["expand_client_home"]
