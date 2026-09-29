"""Which plane must run a QA evidence write from this machine.

A process holding a ``*-db-admin`` connection is a database door into a
universe some other build serves. That build owns the artifact store every
reviewer reads through ``qa.artifact.read``, so evidence written through the
door would land on this machine's disk, readable here and nowhere a reviewer
looks. Evidence writes from such a process relay to the https plane serving
the same universe instead; every other process runs them where it always did.

Client-side by construction: the answer comes from this machine's declared
connections, so a CLI-only install can apply it before dispatch.
"""

from __future__ import annotations

from typing import Optional

from yoke_contracts.machine_config import runtime as machine_config_runtime
from yoke_contracts.machine_config.schema import (
    DB_ADMIN_ENV_SUFFIX,
    same_universe_https_env,
)
from yoke_contracts.schema_authority import serving_build_authority_declared

EVIDENCE_PLANE_UNRESOLVED = "evidence_plane_unresolved"

#: QA functions that write evidence bytes or the handle naming them.
EVIDENCE_WRITE_FUNCTIONS = frozenset(
    {"qa.artifact.add", "qa.artifact.presign", "qa.artifact.rehome"}
)


class EvidencePlaneUnresolved(RuntimeError):
    """A database door names no https plane that could store its evidence."""

    code = EVIDENCE_PLANE_UNRESOLVED


def administered_elsewhere_env() -> str:
    """The ``*-db-admin`` label when another build serves this universe.

    Empty for a local universe, for an https connection (whose calls already
    execute on the serving build), and for a process that declared it serves
    the database it holds.
    """
    if serving_build_authority_declared():
        return ""
    try:
        env = str(machine_config_runtime.active_env() or "")
    except Exception:  # noqa: BLE001 - no readable selection is no admin door
        return ""
    return env if env.endswith(DB_ADMIN_ENV_SUFFIX) else ""


def serving_env_label(admin_env: str) -> str:
    """The https label paired with one ``*-db-admin`` label."""
    return admin_env[: -len(DB_ADMIN_ENV_SUFFIX)]


def evidence_relay_env(function_id: str) -> Optional[str]:
    """The https env that must run *function_id* from here, or None."""
    if function_id not in EVIDENCE_WRITE_FUNCTIONS:
        return None
    admin = administered_elsewhere_env()
    if not admin:
        return None
    served = same_universe_https_env(machine_config_runtime.load_config(), admin)
    if served:
        return served
    base = serving_env_label(admin)
    raise EvidencePlaneUnresolved(
        f"connection {admin!r} administers a universe served elsewhere, but its "
        f"https plane {base!r} is not configured here, so {function_id} has no "
        "store a reviewer can read. Configure it with `yoke connection set "
        f"{base} --api-url ...`, then re-run the capture."
    )


__all__ = [
    "EVIDENCE_PLANE_UNRESOLVED",
    "EVIDENCE_WRITE_FUNCTIONS",
    "EvidencePlaneUnresolved",
    "administered_elsewhere_env",
    "evidence_relay_env",
    "serving_env_label",
]
