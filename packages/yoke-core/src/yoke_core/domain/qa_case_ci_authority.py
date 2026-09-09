"""Which control plane a verification gate asks about GitHub Actions.

GitHub App private keys live on control-plane hosts, never on the machine
running a gate, so every Actions call a gate makes is relayed. Live
delivery and verification both read GitHub through the project's own
control plane — the https sibling of an owner-only database connection.
Stage is a test environment for that live plane, not a topology peer.
"""

from __future__ import annotations

import contextlib
import os
from typing import Iterator

from yoke_contracts.github_workflow_dispatch import (
    GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV,
)


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
    from yoke_core.domain.control_plane_transport import (
        ServingControlPlaneUnresolved,
        serving_control_plane_env,
    )

    try:
        owning_env = serving_control_plane_env()
    except ServingControlPlaneUnresolved:
        # This selection is an optimization: GitHub Actions calls have their
        # own resolution, so a machine that cannot name its plane is left
        # alone rather than refused.
        owning_env = ""
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
]
