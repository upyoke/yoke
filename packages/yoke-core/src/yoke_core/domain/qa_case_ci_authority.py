"""Which control plane a verification gate asks about GitHub Actions.

GitHub App private keys live on control-plane hosts, never on the machine
running a gate, so every Actions call a gate makes is relayed. Choosing
*which* plane relays it is the whole question this module answers, and it
is not the answer a deploy needs.

A deploy reads status through an independently deployed peer, because it
may be replacing the very service it is asking. A verification gate
replaces nothing, and inheriting that peer costs it twice: the peer is a
different universe, and it holds no App authorization for this project's
repository. The plane a gate asks is the one whose rows it is already
working in.
"""

from __future__ import annotations

import contextlib
import os
from typing import Iterator

from yoke_contracts.github_workflow_dispatch import (
    GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV,
)


def owning_control_plane_env() -> str:
    """The https plane holding GitHub App authority for this session's rows.

    An https connection *is* that plane. A direct-Postgres admin connection
    is not a plane at all — it is an owner-only door into one universe's
    database — so the plane that answers for the same universe is its https
    sibling. Returns ``""`` when neither resolves.
    """
    try:
        from yoke_cli.transport.https import resolve_https_connection

        https = resolve_https_connection()
    except Exception:  # noqa: BLE001 - an unusable connection selects nothing
        https = None
    if https is not None:
        return str(https.env or "")
    try:
        from yoke_cli.config import machine_config
        from yoke_contracts.machine_config.schema import same_universe_https_env

        return same_universe_https_env(
            machine_config.load_config(), machine_config.active_env(),
        )
    except Exception:  # noqa: BLE001 - an unreadable config pairs with nothing
        return ""


@contextlib.contextmanager
def github_actions_authority() -> Iterator[None]:
    """Point GitHub Actions calls at the control plane that owns this project.

    Selects the connection itself when it is https, otherwise the https
    plane the direct-Postgres connection administers. An explicit operator
    selection always wins, and a machine where neither resolves is left
    alone for the deployment layer's own resolution to answer.
    """
    from yoke_core.domain.deploy_pipeline_reporting import (
        GITHUB_ACTIONS_RELAY_ENV,
    )

    preselected = (
        os.environ.get(GITHUB_ACTIONS_RELAY_ENV, "").strip()
        or os.environ.get(GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV, "").strip()
    )
    if preselected:
        yield
        return
    owning_env = owning_control_plane_env()
    if not owning_env:
        yield
        return
    os.environ[GITHUB_ACTIONS_RELAY_ENV] = owning_env
    try:
        yield
    finally:
        os.environ.pop(GITHUB_ACTIONS_RELAY_ENV, None)


__all__ = [
    "GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV",
    "github_actions_authority",
    "owning_control_plane_env",
]
