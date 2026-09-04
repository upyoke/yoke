"""Render a launch preview: what it would do, and every machine it weighed."""

from __future__ import annotations

from typing import Any, Mapping, TextIO

from yoke_cli.commands.adapters.session_control_human_output import (
    Column,
    humanize,
    utc_time,
    write_summary,
    write_table,
)


def _machine_capacity(result: Mapping[str, Any]) -> str | None:
    """Each considered machine's lanes against its cap, full ones flagged."""
    entries = result.get("machine_capacity")
    if not isinstance(entries, list) or not entries:
        return None
    parts = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        flag = " AT CAP" if entry.get("at_capacity") else ""
        parts.append(f"{entry.get('machine_id')}: {entry.get('summary')}{flag}")
    return "; ".join(parts) or None


def _headroom_cell(row: Mapping[str, Any]) -> str:
    """Name the reading and the meter that produced it, or say it is missing."""
    headroom = row.get("headroom_percent")
    if headroom is None:
        return "unreadable"
    window = row.get("headroom_window") or "plan limits"
    return f"{int(round(float(headroom)))}% ({window})"


def _usable_cell(row: Mapping[str, Any]) -> str:
    if row.get("may_use"):
        return "yes"
    return row.get("denial_reason") or "no"


def write_launch_preview(result: Mapping[str, Any], stdout: TextIO) -> None:
    selected = result.get("selected_relay")
    selected_row = selected if isinstance(selected, Mapping) else {}
    requested_model = result.get("requested_model")
    # What the launch would carry, which is what registration verifies. A
    # payload that names no resolved model falls back to the caller's ask.
    carried_model = result.get("model") or requested_model
    write_summary(
        "LAUNCH PREVIEW",
        [
            ("Outcome", humanize(result.get("outcome"))),
            ("Requested surface", result.get("requested_surface")),
            ("Requested model", requested_model),
            ("Model this launch would carry", carried_model),
            ("Model decided by", result.get("model_source")),
            (
                "Model verification",
                "at session registration" if carried_model else "not requested",
            ),
            ("Selected surface", result.get("selected_surface")),
            ("Fallback used", bool(result.get("fallback_used"))),
            ("Launchable", bool(result.get("launchable"))),
            (
                "Considered machines",
                ", ".join(result.get("considered_machine_ids") or []),
            ),
            (
                "Eligibility failures",
                ", ".join(
                    humanize(code) for code in result.get("rejection_codes") or []
                ),
            ),
            (
                "Enable command",
                "surface_disabled" in (result.get("rejection_codes") or [])
                and "yoke session-control surface-policy enable --machine M --surface S"
                or None,
            ),
            ("Selected relay", selected_row.get("relay_id")),
            ("Selected machine", selected_row.get("machine_id")),
            ("Machine capacity", _machine_capacity(result)),
            ("Placement", result.get("placement_reason")),
        ],
        stdout,
    )
    placement_columns: tuple[Column, ...] = (
        ("MACHINE", lambda row: row.get("machine_id"), None),
        ("HOST", lambda row: row.get("hostname"), 20),
        ("SURFACE", lambda row: row.get("surface"), 20),
        ("HEADROOM", _headroom_cell, 34),
        ("LANES", lambda row: row.get("capacity_summary") or "-", 30),
        ("OWNED", lambda row: "yes" if row.get("owned_by_requester") else "no", 6),
        ("USABLE", _usable_cell, 30),
        ("CHOSEN", lambda row: "yes" if row.get("selected") else "", 7),
    )
    write_table(
        "MACHINES WEIGHED",
        placement_columns,
        result.get("machine_candidates") or [],
        stdout,
        empty="No machines were weighed.",
    )
    columns: tuple[Column, ...] = (
        ("RELAY", lambda row: row.get("relay_id"), None),
        ("MACHINE", lambda row: row.get("machine_id"), None),
        ("SURFACE", lambda row: row.get("surface"), 20),
        ("VERSION", lambda row: row.get("version"), 18),
        ("LAST SEEN (UTC)", lambda row: utc_time(row.get("last_seen_at")), 22),
    )
    write_table(
        "ELIGIBLE RELAYS",
        columns,
        result.get("eligible_relays") or [],
        stdout,
        empty="No eligible relays found.",
    )
