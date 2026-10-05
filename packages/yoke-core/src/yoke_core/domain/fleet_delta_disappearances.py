"""Explain rows removed from consecutive displayed fleet reports, without reads."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from yoke_core.domain.fleet_delta_snapshot import FleetSnapshot
from yoke_core.domain.steering_fleet_report_render_text import SECTION_LIMIT

ROW_SECTIONS = (
    "landings",
    "idle",
    "in_flight",
    "suspected_orphaned_waiters",
    "landed_open",
    "dead_waits",
    "vendor_errors",
    "stranded",
    "deployment_runs",
)


@dataclass(frozen=True)
class ShownRow:
    scope: str
    section: str
    subject: str
    session_id: str
    facts: Mapping[str, Any]

    @property
    def key(self) -> tuple[str, str, str, str]:
        return self.scope, self.section, self.subject, self.session_id


def _scopes(report: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    return {
        str(scope.get("descriptor") or scope.get("project_id") or "scope"): scope
        for scope in report.get("scopes", (report,))
    }


def shown_rows(
    report: Mapping[str, Any], *, digest: bool
) -> dict[tuple[str, str, str, str], ShownRow]:
    """Retain identities actually displayed, excluding suppressed holder rows."""
    found = {}
    for descriptor, scope in _scopes(report).items():
        landed = {row.get("item_id") for row in scope.get("landed_open", ())}
        sections = ROW_SECTIONS if digest else (*ROW_SECTIONS, "holders")
        named = {
            row.get("session_id")
            for section in (
                "idle",
                "in_flight",
                "suspected_orphaned_waiters",
                "stranded",
            )
            for row in scope.get(section, ())
        }
        for section in sections:
            rows = list(scope.get(section, ()))
            if section in ("idle", "suspected_orphaned_waiters", "holders"):
                rows = [row for row in rows if row.get("item_id") not in landed]
            if section == "holders":
                rows = [row for row in rows if row.get("session_id") not in named]
            if section not in ("in_flight", "stranded"):
                rows = rows[:SECTION_LIMIT]
            for row in rows:
                subject = str(
                    row.get("public_ref")
                    or row.get("run_id")
                    or row.get("session_id")
                    or ""
                )
                if not subject:
                    continue
                entry = ShownRow(
                    descriptor,
                    section,
                    subject,
                    str(row.get("session_id") or row.get("holder_session_id") or ""),
                    dict(row),
                )
                found[entry.key] = entry
    return found


def _item_rows(
    scope: Mapping[str, Any], section: str, subject: str
) -> list[Mapping[str, Any]]:
    return [row for row in scope.get(section, ()) if row.get("public_ref") == subject]


def _reason(
    row: ShownRow, scope: Mapping[str, Any], snapshot: FleetSnapshot | None
) -> str:
    if row.section == "deployment_runs":
        if "deployment_runs" not in scope:
            return "run state unavailable; check `yoke steering report get`"
        if any(run.get("run_id") == row.subject for run in scope["deployment_runs"]):
            return "outside the displayed section limit"
        # This section is the complete live-run set, filtered by terminal status.
        return "run finished (no longer live)"
    landings = _item_rows(scope, "landings", row.subject)
    if any(landing.get("merged") is True for landing in landings) or _item_rows(
        scope, "landed_open", row.subject
    ):
        return "pull request merged"
    if any(landing.get("closed") is True for landing in landings):
        return "pull request closed"
    if row.section == "landings" and row.facts.get("merged") is True:
        return "pull request merged"
    if row.section == "landings" and row.facts.get("closed") is True:
        return "pull request closed"
    if any(
        entry.get("public_ref") == row.subject
        and str(entry.get("session_id") or entry.get("holder_session_id") or "")
        == row.session_id
        for entry in scope.get(row.section, ())
    ):
        return "outside the displayed section limit"
    holders = _item_rows(scope, "holders", row.subject)
    session_id = row.session_id or str(next(iter(holders), {}).get("session_id") or "")
    session = snapshot.sessions.get(session_id) if snapshot else None
    if session is not None and session.lifecycle != "live":
        return f"worker {session.lifecycle}"
    if (session is not None and row.subject not in session.claimed_items) or (
        "holders" in scope
        and row.subject != session_id
        and (
            not holders
            or (
                row.session_id
                and all(
                    holder.get("session_id") != row.session_id for holder in holders
                )
            )
        )
    ):
        return "claim released"
    if session is not None and session.parked:
        return "worker parked"
    if any(holder.get("parked") for holder in holders):
        return "worker parked"
    idle_limit = scope.get("idle_after_seconds")
    if idle_limit is not None and any(
        holder.get("idle_seconds") is not None and holder["idle_seconds"] < idle_limit
        for holder in holders
    ):
        return "worker active again"
    if (
        session is not None
        and session.activity_at is not None
        and snapshot is not None
        and idle_limit is not None
    ):
        if (snapshot.taken_at - session.activity_at).total_seconds() < idle_limit:
            return "worker active again"
    if _item_rows(scope, "in_flight", row.subject):
        return "holder now inside a long-running call"
    if _item_rows(scope, "idle", row.subject):
        return "holder now listed as idle"
    if any(
        entry.get("public_ref") == row.subject for entry in scope.get(row.section, ())
    ):
        return "outside the displayed section limit"
    return "row no longer meets report criteria; current cause unavailable; check `yoke steering report get`"


def disappeared_lines(
    previous: Mapping[tuple[str, str, str, str], ShownRow],
    current: Mapping[tuple[str, str, str, str], ShownRow],
    report: Mapping[str, Any],
    snapshot: FleetSnapshot | None,
) -> list[str]:
    """One explanation per removed row; the caller then replaces its memory."""
    scopes = _scopes(report)
    lines = []
    for key in sorted(previous.keys() - current.keys()):
        row = previous[key]
        scope = scopes.get(row.scope)
        reason = (
            "scope no longer held" if scope is None else _reason(row, scope, snapshot)
        )
        context = ""
        if row.section == "landings" and row.facts.get("pr_number"):
            landing = next(iter(_item_rows(scope or {}, "landings", row.subject)), None)
            facts = landing or row.facts
            observed = "" if landing else "last observed "
            detail = facts.get("narrative") or f"pull request {facts['pr_number']}"
            context = f" ({observed}{detail})"
        lines.append(
            f"  {row.scope} · {row.subject} [{row.section}]  no longer listed — {reason}{context}"
        )
    return lines
