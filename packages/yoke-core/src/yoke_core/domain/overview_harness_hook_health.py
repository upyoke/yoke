"""Harness activation targets, their worded status, and their hook health.

Every supported harness surface is answered for, because "we detect nothing
here" is itself an answer the viewer needs: a surface the machine never
reported reads ``not_installed`` rather than vanishing from the list.

The status is the meaning; colour is a secondary cue on top of it:

* ``green`` — hook-fed telemetry is present inside the health window
* ``orange`` — the harness is installed but has no telemetry in that window
* ``red`` — a current session stayed silent past grace, or hook approval is
  explicitly untrusted
* no colour — nothing is detected for this surface, or a brand-new episode
  is still inside its grace window

Statuses are engine vocabulary; the words a viewer reads are the web copy
deck's job, one line per status token.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from yoke_contracts.harness_hook_approval import hook_approval
from yoke_core.domain.time_parse import parse_timestamp_utc

HOOK_HEALTH_GREEN = "green"
HOOK_HEALTH_ORANGE = "orange"
HOOK_HEALTH_RED = "red"

#: One status per target, most specific first. Each names what we detected,
#: never how sure we are.
STATUS_ACTIVE = "active"
STATUS_HOOKS_NEED_TRUST = "hooks_need_trust"
STATUS_INSTALLED_LAST_SEEN = "installed_last_seen"
STATUS_HOOKS_TRUSTED = "hooks_trusted"
STATUS_INSTALLED_NEVER_SEEN = "installed_never_seen"
STATUS_NOT_INSTALLED = "not_installed"

#: Telemetry older than this is history, not evidence that the installed
#: surface is currently working. Five-week-old sessions therefore render as
#: installed-but-idle instead of either green or broken.
HOOK_TELEMETRY_WINDOW = timedelta(days=30)

#: A SessionStart-registered row with no tool telemetry is also what a
#: healthy brand-new episode looks like. Stay uncoloured until this
#: window elapses.
NEW_EPISODE_GRACE = timedelta(seconds=120)

MATCH_FAMILY = "family"
MATCH_SURFACE_ALIAS = "surface_alias"

HARNESS_TARGETS: Tuple[Tuple[str, str, str, str], ...] = (
    ("claude-code", "Claude Code", "claude-code", MATCH_FAMILY),
    ("codex", "Codex", "codex", MATCH_FAMILY),
    ("cursor", "Cursor", "cursor", MATCH_FAMILY),
    ("claude-cli", "Claude CLI", "claude-code", MATCH_SURFACE_ALIAS),
    ("codex-cli", "Codex CLI", "codex", MATCH_SURFACE_ALIAS),
    ("cursor-cli", "Cursor CLI", "cursor", MATCH_SURFACE_ALIAS),
    ("claude-vscode", "Claude in VS Code", "claude-code", MATCH_SURFACE_ALIAS),
    ("cursor-desktop", "Cursor IDE", "cursor", MATCH_SURFACE_ALIAS),
)

#: Surface aliases per harness family, so a family target counts as
#: installed when any of its own surfaces reported a version.
FAMILY_SURFACES: Dict[str, Tuple[str, ...]] = {
    harness_id: tuple(
        key for key, _label, family, rule in HARNESS_TARGETS
        if family == harness_id and rule == MATCH_SURFACE_ALIAS
    )
    for _key, _label, harness_id, _rule in HARNESS_TARGETS
}


def _matches(
    target: Tuple[str, str, str, str], executor: str, display: str,
) -> bool:
    key, _label, harness_id, rule = target
    if rule == MATCH_SURFACE_ALIAS:
        return display == key
    if executor != harness_id:
        return False
    return rule == MATCH_FAMILY


def _installed_version(
    target: Tuple[str, str, str, str], installed: Mapping[str, Any],
) -> Optional[str]:
    """The relay-reported version for this target, when it reported one.

    A family target has no surface of its own, so it reads the version of
    whichever of its surfaces the relay named.
    """
    key, _label, harness_id, rule = target
    keys = (key,) if rule == MATCH_SURFACE_ALIAS else FAMILY_SURFACES[harness_id]
    for candidate in keys:
        if candidate in installed:
            version = installed[candidate]
            return str(version) if version else None
    return None


def _is_installed(
    target: Tuple[str, str, str, str], installed: Mapping[str, Any],
) -> bool:
    key, _label, harness_id, rule = target
    if rule == MATCH_SURFACE_ALIAS:
        return key in installed
    return any(surface in installed for surface in FAMILY_SURFACES[harness_id])


def _has_telemetry(row: Mapping[str, Any]) -> bool:
    return bool(row.get("hook_fed") or row.get("last_tool_call_at"))


def _in_grace(row: Mapping[str, Any], *, now: datetime) -> bool:
    if _has_telemetry(row):
        return False
    started = parse_timestamp_utc(row.get("episode_started_at"))
    if started is None:
        return False
    return (now - started) < NEW_EPISODE_GRACE


def _activity_at(row: Mapping[str, Any]) -> Optional[datetime]:
    candidates = (
        parse_timestamp_utc(row.get("last_tool_call_at")),
        parse_timestamp_utc(row.get("seen_at")),
    )
    return max((value for value in candidates if value is not None), default=None)


def _in_telemetry_window(row: Mapping[str, Any], *, now: datetime) -> bool:
    activity = _activity_at(row)
    return activity is not None and (now - activity) <= HOOK_TELEMETRY_WINDOW


def _last_seen_at(matched: Sequence[Mapping[str, Any]]) -> Optional[str]:
    seen = [
        (parsed, str(value))
        for row in matched
        if (value := row.get("seen_at")) is not None
        if (parsed := parse_timestamp_utc(value)) is not None
    ]
    return max(seen, key=lambda entry: entry[0])[1] if seen else None


def _report_for(
    reports: Sequence[Mapping[str, Any]], harness_id: str,
) -> Optional[Mapping[str, Any]]:
    matched = [row for row in reports if row.get("harness_id") == harness_id]
    if not matched:
        return None
    merged: Dict[str, Any] = {
        "harness_id": harness_id,
        "glue_written": any(row.get("glue_written") for row in matched),
        "glue_present": any(row.get("glue_present") for row in matched),
        "glue_malformed": any(row.get("glue_malformed") for row in matched),
        "config_present": any(row.get("config_present") for row in matched),
        "project_entry_present": any(
            row.get("project_entry_present") for row in matched
        ),
        "approval_state": "not_applicable",
    }
    if any(row.get("approval_state") == "unapproved" for row in matched):
        merged["approval_state"] = "unapproved"
    elif any(row.get("approval_state") == "approved" for row in matched):
        merged["approval_state"] = "approved"
    return merged


def _report_lists(report: Optional[Mapping[str, Any]]) -> bool:
    if report is None:
        return False
    return any(
        report.get(key)
        for key in (
            "config_present",
            "glue_present",
            "glue_written",
            "project_entry_present",
        )
    )


def _approval(report: Optional[Mapping[str, Any]]) -> Optional[str]:
    return None if report is None else report.get("approval_state")


def _status(
    matched: Sequence[Mapping[str, Any]],
    report: Optional[Mapping[str, Any]],
    *,
    installed: bool,
    last_seen: Optional[str],
    now: datetime,
) -> str:
    """The one thing this target's card says, from what we detected."""
    recent = [row for row in matched if _in_telemetry_window(row, now=now)]
    if any(_has_telemetry(row) for row in recent):
        return STATUS_ACTIVE
    if _approval(report) == "unapproved":
        return STATUS_HOOKS_NEED_TRUST
    if last_seen:
        return STATUS_INSTALLED_LAST_SEEN
    if _approval(report) == "approved":
        return STATUS_HOOKS_TRUSTED
    if installed or matched or _report_lists(report):
        return STATUS_INSTALLED_NEVER_SEEN
    return STATUS_NOT_INSTALLED


def _health(
    matched: Sequence[Mapping[str, Any]],
    report: Optional[Mapping[str, Any]],
    *,
    installed: bool,
    now: datetime,
) -> Optional[str]:
    recent = [row for row in matched if _in_telemetry_window(row, now=now)]
    if any(_has_telemetry(row) for row in recent):
        return HOOK_HEALTH_GREEN
    if _approval(report) == "unapproved":
        return HOOK_HEALTH_RED
    if recent and all(_in_grace(row, now=now) for row in recent):
        return None
    if recent:
        return HOOK_HEALTH_RED
    if installed or matched or _report_lists(report):
        return HOOK_HEALTH_ORANGE
    return None


def harness_targets(
    identities: Sequence[Mapping[str, Any]],
    reports: Sequence[Mapping[str, Any]] | None = None,
    *,
    installed_surfaces: Mapping[str, Any] | None = None,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Render every target with its worded status and live hook health.

    ``identities`` are per-identity maps with ``executor``, ``display``,
    optional ``hook_fed``, ``last_tool_call_at``, ``episode_started_at``,
    and ``seen_at``. ``reports`` are this machine's own report rows keyed by
    ``harness_id``; ``installed_surfaces`` maps a relay-reported surface
    alias on this machine to the version it reported.
    """
    clock = now or datetime.now(timezone.utc)
    stored = list(reports or ())
    installed = dict(installed_surfaces or {})
    targets: List[Dict[str, Any]] = []
    for target in HARNESS_TARGETS:
        key, label, harness_id, _rule = target
        matched = [
            row for row in identities
            if _matches(target, str(row.get("executor") or ""), str(row.get("display") or ""))
        ]
        report = _report_for(stored, harness_id)
        surface_installed = _is_installed(target, installed)
        last_seen = _last_seen_at(matched)
        gate = hook_approval(harness_id)
        unapproved = _approval(report) == "unapproved"
        targets.append({
            "key": key,
            "label": label,
            "hit": bool(matched),
            "version": _installed_version(target, installed),
            "status": _status(
                matched, report, installed=surface_installed,
                last_seen=last_seen, now=clock,
            ),
            "hook_health": _health(
                matched, report, installed=surface_installed, now=clock,
            ),
            "last_seen_at": last_seen,
            "trust_surface": (
                gate["trust_surface"] if gate is not None and unapproved else None
            ),
        })
    return targets


def session_identities(rows: Iterable[Sequence[Any]]) -> List[Dict[str, Any]]:
    """Normalize executor, surface, telemetry, episode, tool, and seen rows."""
    identities: List[Dict[str, Any]] = []
    for row in rows:
        identities.append({
            "executor": str(row[0]),
            "display": str(row[1] or ""),
            "hook_fed": int(row[2] or 0),
            "episode_started_at": row[3] if len(row) > 3 else None,
            "last_tool_call_at": row[4] if len(row) > 4 else None,
            "seen_at": row[5] if len(row) > 5 else None,
        })
    return identities


__all__ = [
    "FAMILY_SURFACES",
    "HARNESS_TARGETS",
    "HOOK_HEALTH_GREEN",
    "HOOK_HEALTH_ORANGE",
    "HOOK_HEALTH_RED",
    "HOOK_TELEMETRY_WINDOW",
    "MATCH_FAMILY",
    "MATCH_SURFACE_ALIAS",
    "NEW_EPISODE_GRACE",
    "STATUS_ACTIVE",
    "STATUS_HOOKS_NEED_TRUST",
    "STATUS_HOOKS_TRUSTED",
    "STATUS_INSTALLED_LAST_SEEN",
    "STATUS_INSTALLED_NEVER_SEEN",
    "STATUS_NOT_INSTALLED",
    "harness_targets",
    "session_identities",
]
