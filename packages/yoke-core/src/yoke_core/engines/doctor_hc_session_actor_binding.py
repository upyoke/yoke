"""Check the recorded local operator holds its universe admin role."""

from __future__ import annotations

from typing import Any

from yoke_core.domain.local_operating_actor import (
    OPERATING_ACTOR_GRANT_REPAIR,
    ensure_local_operating_actor,
    holds_org_admin,
)
from yoke_core.domain.session_actor_binding import resolve_operating_actor

import yoke_core.engines.doctor_report as _base
from yoke_core.engines.doctor_report import DoctorArgs, RecordCollector


AUTHORITY_SLUG = "local-operating-actor-authority"
AUTHORITY_TITLE = "The local universe's operating actor holds its org admin role"


def hc_local_operating_actor_authority(
    conn: Any, args: DoctorArgs, rec: RecordCollector
) -> None:
    """Flag — and under ``--fix`` grant — the local operator's org admin role.

    This question belongs to the machine-local universe whose database stores
    the operating actor and its grant. An HTTPS-connected local runner acts on
    a remote universe instead, so the check's applicability declaration marks
    that run N/A rather than inventing a local actor or dereferencing the
    absent local connection.
    """
    for table in ("actors", "actor_org_roles", "organizations"):
        if not _base._table_exists(conn, table):
            rec.record(
                AUTHORITY_SLUG,
                AUTHORITY_TITLE,
                "PASS",
                f"{table} table missing — nothing to check",
            )
            return

    binding = resolve_operating_actor(conn)
    if not binding.bound:
        rec.record(AUTHORITY_SLUG, AUTHORITY_TITLE, "FAIL", binding.detail)
        return

    actor_id = int(binding.actor_id)
    if holds_org_admin(conn, actor_id):
        rec.record(
            AUTHORITY_SLUG,
            AUTHORITY_TITLE,
            "PASS",
            f"actor {actor_id} holds the org admin role",
        )
        return

    if args.fix:
        ensure_local_operating_actor(conn)
        if holds_org_admin(conn, actor_id):
            rec.record(
                AUTHORITY_SLUG,
                AUTHORITY_TITLE,
                "PASS",
                f"--fix: granted actor {actor_id} the org admin role",
            )
            return

    rec.record(
        AUTHORITY_SLUG,
        AUTHORITY_TITLE,
        "FAIL",
        f"actor {actor_id} operates this universe but holds no org admin "
        "role, so the dispatcher denies every mutation its sessions "
        f"attempt. Repair: `{OPERATING_ACTOR_GRANT_REPAIR}`, which grants "
        "exactly that role on this universe's own org.",
    )


__all__ = [
    "AUTHORITY_SLUG",
    "AUTHORITY_TITLE",
    "hc_local_operating_actor_authority",
]
