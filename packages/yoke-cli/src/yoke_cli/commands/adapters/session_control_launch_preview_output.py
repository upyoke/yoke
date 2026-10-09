"""Render a launch preview: what it would do, and every machine it weighed."""

from __future__ import annotations

from typing import Any, Mapping, TextIO

from yoke_contracts.session_control.model_billing_pools import (
    MODEL_UNNAMED,
    NO_POOL_WINDOW,
    POOL_UNREADABLE,
)
from yoke_cli.commands.adapters.session_control_level_placement_output import (
    level_rows,
    write_level_candidates,
)
from yoke_cli.commands.adapters.session_control_human_output import (
    Column,
    EMPTY_VALUE,
    humanize,
    write_summary,
    write_table,
)


def selection_rows(label: str, requested: Any, effective: Any) -> list[tuple[str, Any]]:
    """Equal selections need one row; changed selections retain both facts."""
    if requested == effective:
        return [(label, effective)]
    return [(f"Requested {label.lower()}", requested), (f"Effective {label.lower()}", effective)]


def nonempty_rows(fields: list[tuple[str, Any]]) -> list[tuple[str, Any]]:
    return [(label, value) for label, value in fields if value is not None and value != "" and value != EMPTY_VALUE]


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


#: One table-width word per reason the reading gives in full sentences, so a
#: cell stays readable without the CLI restating the policy behind it.
_POOL_CELL_LABELS = {
    NO_POOL_WINDOW: "no meter",
    POOL_UNREADABLE: "unreadable",
    MODEL_UNNAMED: "no model named",
}


def _model_pool_cell(row: Mapping[str, Any]) -> str:
    """Say what the requested model's own billing pool reads.

    Headroom is runway over time-to-reset; this is the raw quota left in the
    pool the model bills to, which is what a fallback decision turns on.
    """
    pool = row.get("model_pool")
    if not isinstance(pool, Mapping):
        return "-"
    name = pool.get("pool") or "unpooled"
    if pool.get("exhausted"):
        return f"{name}: exhausted"
    remaining = pool.get("remaining_percent")
    if remaining is None:
        return f"{name}: {_POOL_CELL_LABELS.get(pool.get('reason'), 'unknown')}"
    return f"{name}: {int(round(float(remaining)))}% left"


def _usable_cell(row: Mapping[str, Any]) -> str:
    if row.get("may_use"):
        return "yes"
    return row.get("denial_reason") or "no"


def write_launch_preview(result: Mapping[str, Any], stdout: TextIO) -> None:
    selected = result.get("selected_relay")
    selected_row = selected if isinstance(selected, Mapping) else {}
    requested_model = result.get("requested_model")
    requested_effort = result.get("requested_reasoning_effort")
    requested_context = result.get("requested_context_window_tokens")
    # What the launch would carry is what registration verifies. Older
    # responses without resolved fields fall back to the caller's ask.
    carried_model = result.get("model") or requested_model
    carried_effort = result.get("reasoning_effort") or requested_effort
    carried_context = result.get("context_window_tokens") or requested_context
    carries_selection = any(
        value is not None for value in (carried_model, carried_effort, carried_context)
    )
    write_summary(
        "LAUNCH PREVIEW",
        nonempty_rows([
            ("Outcome", humanize(result.get("outcome"))),
            *level_rows(result.get("level_placement")),
            ("Requested surface", result.get("requested_surface")),
            *selection_rows("Model", requested_model, carried_model),
            *selection_rows("Effort", requested_effort, carried_effort),
            *selection_rows("Context tokens", requested_context, carried_context),
            ("Model decided by", result.get("model_source")),
            ("Effort decided by", result.get("reasoning_effort_source")),
            ("Context decided by", result.get("context_window_source")),
            (
                "Selection verification",
                "at session registration" if carries_selection else "not requested",
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
        ]),
        stdout,
    )
    write_level_candidates(result.get("level_placement"), stdout)
    placement_columns: tuple[Column, ...] = (
        ("MACHINE", lambda row: row.get("machine_id"), None),
        ("HOST", lambda row: row.get("hostname"), 20),
        ("SURFACE", lambda row: row.get("surface"), 20),
        ("HEADROOM", _headroom_cell, 34),
        ("REQUESTED MODEL POOL", _model_pool_cell, 34),
        ("LANES", lambda row: row.get("capacity_summary") or "-", 30),
        ("OWNED", lambda row: "yes" if row.get("owned_by_requester") else "no", 6),
        ("USABLE", _usable_cell, 30),
        ("CHOSEN", lambda row: "yes" if row.get("selected") else "", 7),
    )
    candidates = result.get("machine_candidates") or []
    if candidates and (len(candidates) > 1 or result.get("placement_reason") or result.get("rejection_codes") or any(not row.get("may_use") or row.get("model_pool") for row in candidates)):
        write_table("MACHINES WEIGHED", placement_columns, candidates, stdout, empty="No machines were weighed.")
