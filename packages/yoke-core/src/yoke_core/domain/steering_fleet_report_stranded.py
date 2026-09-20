"""Sessions that cannot return, named instead of quiet.

A wake against an exhausted meter dies. A session still pinned to a model
the machine no longer selects, or to one its surface no longer offers, is
the same shape: the control plane already knows, and silence is the wrong
report. This detector reads that published state — the meters, the
preferred map, the native availability, a credential rejection the vendor
already classified — and names the recovery. It never relaunches and never
substitutes a model; those stay the operator's call.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Mapping

from yoke_contracts.session_control.native_models import (
    available_models,
    sanitize_native_models,
)
from yoke_core.domain.item_ref_render import render_item_refs
from yoke_core.domain.session_relay_types import advertised_session_models
from yoke_core.domain.session_wake_meter import (
    MeterWall,
    RECOVERY,
    meter_wall,
    pinned_model,
)
from yoke_core.domain.session_vendor_error_states import vendor_error_states
from yoke_core.domain.steering_fleet_report_detectors import marker
from yoke_core.domain.steering_fleet_report_limits import (
    MachinePlanLimit,
    load_plan_limits,
)
from yoke_core.domain.steering_fleet_report_render_text import SECTION_LIMIT, capped
from yoke_core.domain.work_claim_targets import scope_int_sql


KIND_METER_EXHAUSTED = "meter_exhausted"
KIND_MODEL_DESELECTED = "model_deselected"
KIND_MODEL_REMOVED = "model_removed"
KIND_CREDENTIAL_REJECTED = "credential_rejected"

_KIND_ORDER = (
    KIND_METER_EXHAUSTED,
    KIND_CREDENTIAL_REJECTED,
    KIND_MODEL_REMOVED,
    KIND_MODEL_DESELECTED,
)


@dataclass(frozen=True)
class StrandedSession:
    """One live session pinned to a model it cannot usefully resume on."""

    session_id: str
    item_id: int
    public_ref: str
    surface: str
    model: str
    kind: str
    preferred_model: str
    meter: str
    remaining_percent: float | None
    resets_at: str
    reason: str
    recovery: str

    @property
    def seat_owed(self) -> bool:
        return True


def _document(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _claimed_items(conn: Any, session_ids: list[str]) -> dict[str, int]:
    if not session_ids:
        return {}
    item_id = scope_int_sql(conn, "c.scope", "item_id")
    slots = ",".join(marker(conn) for _ in session_ids)
    rows = conn.execute(
        f"SELECT c.session_id AS session_id, {item_id} AS item_id "
        "FROM work_claims c "
        "WHERE c.target_kind='item' AND c.released_at IS NULL "
        f"AND c.session_id IN ({slots})",
        tuple(session_ids),
    ).fetchall()
    claimed: dict[str, int] = {}
    for raw in rows:
        record = dict(raw)
        try:
            claimed[str(record["session_id"])] = int(record["item_id"])
        except (TypeError, ValueError):
            continue
    return claimed


def _live_sessions(conn: Any, *, project_id: int) -> list[dict[str, Any]]:
    placeholder = marker(conn)
    rows = conn.execute(
        "SELECT session_id, project_id, machine_id, executor_surface, "
        "model, requested_model FROM harness_sessions "
        "WHERE ended_at IS NULL AND terminated_at IS NULL "
        f"AND project_id={placeholder} "
        "ORDER BY session_id",
        (int(project_id),),
    ).fetchall()
    return [dict(row) for row in rows]


def _relay_maps(
    conn: Any, *, machine_id: str, now: str
) -> tuple[dict[str, str], Mapping[str, Any]]:
    placeholder = marker(conn)
    row = conn.execute(
        "SELECT preferred_session_models, surface_native_models "
        "FROM session_relays "
        f"WHERE machine_id={placeholder} AND connected_until>={placeholder} "
        "ORDER BY last_seen_at DESC, relay_id DESC",
        (machine_id, now),
    ).fetchone()
    if row is None:
        return {}, {}
    record = dict(row)
    preferred = advertised_session_models(
        _document(record.get("preferred_session_models"))
    )
    native = sanitize_native_models(_document(record.get("surface_native_models")))
    return preferred, native


def _kinds_for(
    row: Mapping[str, Any],
    *,
    wall: MeterWall | None,
    preferred: str,
    native_models: tuple[str, ...],
    credential_rejected: bool,
) -> tuple[str, ...]:
    model = pinned_model(row)
    kinds: list[str] = []
    if wall is not None:
        kinds.append(KIND_METER_EXHAUSTED)
    if credential_rejected:
        kinds.append(KIND_CREDENTIAL_REJECTED)
    if native_models and model and model not in native_models:
        kinds.append(KIND_MODEL_REMOVED)
    if preferred and model and preferred != model:
        kinds.append(KIND_MODEL_DESELECTED)
    return tuple(kind for kind in _KIND_ORDER if kind in kinds)


def _reason(
    kind: str,
    *,
    wall: MeterWall | None,
    preferred: str,
    model: str,
) -> tuple[str, str]:
    if kind == KIND_METER_EXHAUSTED and wall is not None:
        quota = f"{int(round(wall.remaining_percent))}%"
        reset = wall.resets_at or "unknown"
        return (
            f"meter {wall.meter} ({wall.window}) {quota} remaining, resets {reset}",
            RECOVERY,
        )
    if kind == KIND_CREDENTIAL_REJECTED:
        return (
            "provider rejected the session's credentials",
            "Fix the account, then relaunch; a wake cannot repair this.",
        )
    if kind == KIND_MODEL_REMOVED:
        return (
            f"pinned to {model}, which this surface no longer offers",
            "Relaunch on a model this surface still selects.",
        )
    return (
        f"pinned to {model}; current preferred is {preferred}",
        "Relaunch deliberately if you want the current default; a wake stays on the old model.",
    )


def stranded_sessions(
    conn: Any,
    *,
    project_id: int,
    now: str,
    limits: tuple[MachinePlanLimit, ...] | None = None,
) -> tuple[StrandedSession, ...]:
    """Live sessions in this project that cannot usefully be woken."""
    live = _live_sessions(conn, project_id=project_id)
    if not live:
        return ()
    limits = (
        limits
        if limits is not None
        else load_plan_limits(conn, project_id=project_id, now=now)
    )
    rejected = {
        str(state.get("session_id") or "")
        for state in vendor_error_states(conn, authorized_projects=(int(project_id),))
        if str(state.get("signature_id") or "") == "auth_rejected"
    }
    claimed = _claimed_items(conn, [str(row["session_id"]) for row in live])
    refs = render_item_refs(conn, sorted(set(claimed.values())))
    found: list[StrandedSession] = []
    relay_cache: dict[str, tuple[dict[str, str], Mapping[str, Any]]] = {}
    for row in live:
        session_id = str(row["session_id"])
        machine_id = str(row.get("machine_id") or "").strip()
        surface = str(row.get("executor_surface") or "").strip()
        model = pinned_model(row)
        if machine_id not in relay_cache:
            relay_cache[machine_id] = _relay_maps(conn, machine_id=machine_id, now=now)
        preferred_map, native_doc = relay_cache[machine_id]
        preferred = preferred_map.get(surface, "")
        native_models = available_models(
            native_doc.get(surface) if native_doc else None
        )
        wall = meter_wall(conn, session_id, now, limits=limits)
        kinds = _kinds_for(
            row,
            wall=wall,
            preferred=preferred,
            native_models=native_models,
            credential_rejected=session_id in rejected,
        )
        if not kinds:
            continue
        kind = kinds[0]
        reason, recovery = _reason(kind, wall=wall, preferred=preferred, model=model)
        item_id = claimed.get(session_id, 0)
        found.append(
            StrandedSession(
                session_id=session_id,
                item_id=item_id,
                public_ref=refs.get(item_id, ""),
                surface=surface,
                model=model,
                kind=kind,
                preferred_model=preferred,
                meter=wall.meter if wall is not None else "",
                remaining_percent=wall.remaining_percent if wall is not None else None,
                resets_at=(wall.resets_at or "") if wall is not None else "",
                reason=reason,
                recovery=recovery,
            )
        )
    return tuple(found)


def stranded_section(report: Any) -> list[str]:
    """The report's stranded-session section, heading included; empty when none."""
    rows: tuple[StrandedSession, ...] = getattr(report, "stranded", ())
    if not rows:
        return []
    grouped: dict[tuple[str, str, str], list[StrandedSession]] = {}
    for entry in rows:
        key = (entry.kind, entry.surface, entry.model)
        grouped.setdefault(key, []).append(entry)
    ordered = sorted(
        grouped.items(),
        key=lambda item: (_KIND_ORDER.index(item[0][0]), item[0][1], item[0][2]),
    )
    lines = [
        (
            f"  {len(group)} session{'s' if len(group) != 1 else ''} on "
            f"{key[1] or 'unknown'} · {key[2] or 'unknown'}  "
            f"{group[0].reason}  "
            f"{', '.join(entry.session_id for entry in group)}  holding "
            f"{', '.join(entry.public_ref or 'no item' for entry in group)}  "
            f"{group[0].recovery}"
        )
        for key, group in ordered
    ]
    return [
        "stranded sessions — pinned to an exhausted or no-longer-selected "
        "model; do not wake them:",
        *capped(lines[:SECTION_LIMIT], len(rows)),
    ]


def stranded_dicts(rows: tuple[StrandedSession, ...]) -> list[dict[str, Any]]:
    return [
        {
            "session_id": entry.session_id,
            "item_id": entry.item_id,
            "public_ref": entry.public_ref or None,
            "surface": entry.surface,
            "model": entry.model,
            "kind": entry.kind,
            "preferred_model": entry.preferred_model or None,
            "meter": entry.meter or None,
            "remaining_percent": entry.remaining_percent,
            "resets_at": entry.resets_at or None,
            "reason": entry.reason,
            "recovery": entry.recovery,
            "seat_owed": entry.seat_owed,
        }
        for entry in rows
    ]


__all__ = [
    "KIND_CREDENTIAL_REJECTED",
    "KIND_METER_EXHAUSTED",
    "KIND_MODEL_DESELECTED",
    "KIND_MODEL_REMOVED",
    "StrandedSession",
    "stranded_dicts",
    "stranded_section",
    "stranded_sessions",
]
