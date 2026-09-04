"""Maintenance work a relay poll carries, none of which may cost it its job.

The poll is the only thing a machine does on a schedule, so it is where
per-machine upkeep lives. Every job here is best-effort around the poll it
rides on: the poll's job is to hand this relay its next wake, and a job that
fails must not take that away. Failures are logged and the poll continues,
because the next poll re-derives the same work from the same durable rows.
"""

from __future__ import annotations

import logging


_LOGGER = logging.getLogger(__name__)


def sweep_quiet_claim_holders(conn, *, machine_id: str, projects) -> None:
    """Probe this machine's silent claim-holders.

    The probe is best-effort around the poll it rides on. The poll's job
    is to hand this relay its next wake; a probe that fails must not take
    that away, so failure is logged and the poll continues — the next poll
    tries again from the same durable rows.
    """
    from yoke_core.domain.session_stale_alive_probe import probe_stale_alive_sessions

    try:
        probe_stale_alive_sessions(
            conn, machine_id=machine_id, authorized_projects=projects
        )
    except Exception:
        _LOGGER.debug(
            "quiet claim-holder probe failed during relay poll", exc_info=True
        )


def resume_vendor_error_sessions(conn, *, machine_id: str, projects, actor_id: int):
    """Resume this machine's sessions whose backoff since a vendor error is up.

    The poll is the only thing this machine does on a schedule, and the
    first attempt is deliberately a minute late, so this cannot be a
    one-shot at observation time — it has to be re-derived every poll from
    the durable rows. Best-effort like the sweeps above: a refused or
    failing resume must not cost the relay the job this poll came for.
    """
    from yoke_core.domain.session_vendor_error_resume import (
        resume_vendor_error_sessions,
    )

    try:
        resume_vendor_error_sessions(
            conn,
            machine_id=machine_id,
            authorized_projects=projects,
            actor_id=actor_id,
        )
    except Exception:
        _LOGGER.debug("vendor-error resume sweep skipped", exc_info=True)


def stuck_native_turn_probes(conn, *, machine_id: str, projects) -> list:
    """Name the sessions this machine should read a turn record back for.

    Best-effort like the sweeps above: a poll whose job is to hand the relay
    its next wake must not be lost to the probe list that would have fixed a
    later one. The next poll re-derives the same targets from the same rows.
    """
    from yoke_core.domain.session_native_turn_end import probe_targets

    try:
        return probe_targets(conn, machine_id=machine_id, authorized_projects=projects)
    except Exception:
        _LOGGER.debug("native turn-end probe targets skipped", exc_info=True)
        return []


__all__ = [
    "resume_vendor_error_sessions",
    "stuck_native_turn_probes",
    "sweep_quiet_claim_holders",
]
