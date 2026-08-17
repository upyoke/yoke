"""Harness activation targets and their live hook health.

Colours say what the operator should do, not how sure we are:

* ``green`` — hook-fed telemetry is present
* ``orange`` — glue is present and approval state is readable and untrusted
* ``red`` — listed, and not yet detected as fully working, after the
  new-episode grace window

Grey is not a colour. A harness with no machine-side evidence and no
matching session is omitted from the list. Approval colouring is driven
by ``approval_state == "unapproved"``, not by a harness-id branch.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from yoke_contracts.harness_hook_approval import hook_approval
from yoke_core.domain.time_parse import parse_timestamp_utc

HOOK_HEALTH_GREEN = "green"
HOOK_HEALTH_ORANGE = "orange"
HOOK_HEALTH_RED = "red"

#: A SessionStart-registered row with no tool telemetry is also what a
#: healthy brand-new episode looks like. Stay uncoloured until this
#: window elapses.
NEW_EPISODE_GRACE = timedelta(seconds=120)

MATCH_FAMILY = "family"
MATCH_BARE_SESSION = "bare_session"
MATCH_SURFACE_ALIAS = "surface_alias"

HARNESS_TARGETS: Tuple[Tuple[str, str, str, str], ...] = (
    ("claude-code", "Claude Code", "claude-code", MATCH_FAMILY),
    ("codex", "Codex", "codex", MATCH_FAMILY),
    ("cursor", "Cursor", "cursor", MATCH_FAMILY),
    ("claude-cli", "Claude CLI", "claude-code", MATCH_BARE_SESSION),
    ("codex-cli", "Codex CLI", "codex", MATCH_BARE_SESSION),
    ("cursor-cli", "Cursor CLI", "cursor", MATCH_SURFACE_ALIAS),
    ("claude-vscode", "Claude in VS Code", "claude-code", MATCH_SURFACE_ALIAS),
    ("cursor-desktop", "Cursor IDE", "cursor", MATCH_SURFACE_ALIAS),
)


def _matches(
    target: Tuple[str, str, str, str], executor: str, display: str,
) -> bool:
    key, _label, harness_id, rule = target
    if rule == MATCH_SURFACE_ALIAS:
        return display == key
    if executor != harness_id:
        return False
    return rule == MATCH_FAMILY or not display


def _has_telemetry(row: Mapping[str, Any]) -> bool:
    return bool(row.get("hook_fed") or row.get("last_tool_call_at"))


def _in_grace(row: Mapping[str, Any], *, now: datetime) -> bool:
    if _has_telemetry(row):
        return False
    started = parse_timestamp_utc(row.get("episode_started_at"))
    if started is None:
        return False
    return (now - started) < NEW_EPISODE_GRACE


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


def _listed(
    matched: Sequence[Mapping[str, Any]], report: Optional[Mapping[str, Any]],
) -> bool:
    if matched:
        return True
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


def _health(
    matched: Sequence[Mapping[str, Any]],
    report: Optional[Mapping[str, Any]],
    *,
    now: datetime,
) -> Optional[str]:
    if any(_has_telemetry(row) for row in matched):
        return HOOK_HEALTH_GREEN
    if report is not None and report.get("approval_state") == "unapproved":
        return HOOK_HEALTH_ORANGE
    if matched and all(_in_grace(row, now=now) for row in matched):
        return None
    return HOOK_HEALTH_RED


def harness_targets(
    identities: Sequence[Mapping[str, Any]],
    reports: Sequence[Mapping[str, Any]] | None = None,
    *,
    now: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    """Render listed targets with live hook health.

    ``identities`` are per-identity maps with ``executor``, ``display``,
    optional ``hook_fed``, ``last_tool_call_at``, and
    ``episode_started_at``. ``reports`` are machine-report rows keyed by
    ``harness_id``.
    """
    clock = now or datetime.now(timezone.utc)
    stored = list(reports or ())
    targets: List[Dict[str, Any]] = []
    for target in HARNESS_TARGETS:
        key, label, harness_id, _rule = target
        matched = [
            row for row in identities
            if _matches(target, str(row.get("executor") or ""), str(row.get("display") or ""))
        ]
        report = _report_for(stored, harness_id)
        if not _listed(matched, report):
            continue
        gate = hook_approval(harness_id)
        targets.append({
            "key": key,
            "label": label,
            "hit": bool(matched),
            "hook_health": _health(matched, report, now=clock),
            "trust_surface": None if gate is None else gate["trust_surface"],
        })
    return targets


def session_identities(rows: Iterable[Sequence[Any]]) -> List[Dict[str, Any]]:
    """Normalize ``(executor, display, hook_fed, episode, last_tool)`` rows."""
    identities: List[Dict[str, Any]] = []
    for row in rows:
        identities.append({
            "executor": str(row[0]),
            "display": str(row[1] or ""),
            "hook_fed": int(row[2] or 0),
            "episode_started_at": row[3] if len(row) > 3 else None,
            "last_tool_call_at": row[4] if len(row) > 4 else None,
        })
    return identities


__all__ = [
    "HARNESS_TARGETS",
    "HOOK_HEALTH_GREEN",
    "HOOK_HEALTH_ORANGE",
    "HOOK_HEALTH_RED",
    "MATCH_BARE_SESSION",
    "MATCH_FAMILY",
    "MATCH_SURFACE_ALIAS",
    "NEW_EPISODE_GRACE",
    "harness_targets",
    "session_identities",
]
