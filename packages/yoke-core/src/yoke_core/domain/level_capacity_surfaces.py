"""Viewer-visible recent machines and one unavailable reason per surface."""

from dataclasses import replace
from datetime import timedelta

from yoke_core.domain.machine_access_authority import actor_may_use_machine


def viewer_snapshot(conn, snapshot, *, actor_id, project_id, now):
    """Apply access, retirement and recency equally to relays and rejections."""
    active = {
        str(row[0])
        for row in conn.execute(
            "SELECT machine_id FROM machines WHERE retired_at IS NULL"
        ).fetchall()
    }
    cutoff = now - timedelta(hours=24)
    allowed = {}

    def visible(entry):
        machine = entry.machine_id
        if machine not in active or entry.last_seen_at is None:
            return False
        if entry.last_seen_at < cutoff:
            return False
        if machine not in allowed:
            allowed[machine] = actor_may_use_machine(
                conn, machine_id=machine, actor_id=actor_id,
                project_id=project_id, is_admin=False,
            ).allowed
        return allowed[machine]

    return replace(
        snapshot,
        relays=tuple(entry for entry in snapshot.relays if visible(entry)),
        machine_rejections=tuple(
            entry for entry in snapshot.machine_rejections if visible(entry)
        ),
    )


def surface_reason(surface, rejection):
    """Name one cause on the freshest machine that actually offers a surface."""
    phrases = (
        ("harness_signed_out", "signed out"),
        ("liveness_expired", "relay disconnected"),
        ("version_below_floor", "below version floor"),
        ("surface_disabled", "surface disabled"),
        ("machine_at_capacity", "at capacity"),
        ("project_checkout_missing", "project checkout missing"),
    )
    phrase = next((text for code, text in phrases if code in rejection.codes), None)
    if phrase is None:
        phrase = ", ".join(rejection.codes)
    reason = f"{surface}: {phrase} on {rejection.name}"
    if "harness_signed_out" in rejection.codes and surface == "claude-cli":
        return reason + " — run `claude /login` there"
    if rejection.recovery:
        reason += " — " + rejection.recovery[0].removesuffix(".").replace("Run ", "run ", 1) + " there"
    return reason
