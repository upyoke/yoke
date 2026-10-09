"""Per-session read checkpoints for the full report's independently held scopes.

Hook/watcher delivery fingerprints cover their actionable digest. Pull reads
also show inventories and machine facts, so their section checkpoints belong
to the same durable session owner without spending a delivery interval.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.steering_fleet_report_compose import (
    CombinedFleetReport,
    COMBINED_PREAMBLE,
)
from yoke_core.domain.steering_fleet_report_fingerprint import digest
from yoke_core.domain.steering_fleet_report_inbox import unacked_section_lines
from yoke_core.domain.steering_fleet_report_machine_block import machine_shared_lines
from yoke_core.domain.steering_fleet_report_projection import report_dict
from yoke_core.domain.steering_fleet_report_project_rows import rows_per_section
from yoke_core.domain.steering_fleet_report_render import scope_inner_body
from yoke_core.domain.steering_fleet_report_levels import level_readout_lines


READ_FINGERPRINTS_COLUMN = "steering_report_read_fingerprints"
READ_FINGERPRINTS_DDL = "TEXT DEFAULT NULL"
_SHARED_FACTS = (
    "launchable", "session_counts", "plan_limits", "machine_capacity",
    "levels", "origin_counts", "relay_health",
)


def _age_blind(value: Any) -> Any:
    """Ages tick between reads; state and threshold crossings remain facts."""
    if isinstance(value, dict):
        return {
            key: _age_blind(item) for key, item in value.items()
            if key != "composed_at" and not key.endswith("_seconds")
            and not key.endswith("_at")
        }
    if isinstance(value, (list, tuple)):
        return [_age_blind(item) for item in value]
    return value


def _sections(combined: CombinedFleetReport) -> dict[str, tuple[str, str]]:
    reports = tuple(section.report for section in combined.sections)
    sections = {}
    for section, rows in zip(combined.sections, rows_per_section(reports)):
        facts = {key: value for key, value in report_dict(section.report).items()
                 if key not in _SHARED_FACTS}
        facts["test_machines"] = section.report.test_machines
        sections[f"scope:{section.descriptor}"] = (
            digest(_age_blind(facts)),
            f"## {section.descriptor}\n{scope_inner_body(section.report, rows)}",
        )
    sections["inbox"] = (
        digest([row.message_id for row in combined.unacked_injected]),
        "\n".join(unacked_section_lines(combined.unacked_injected)) or "unacked inbox: none",
    )
    sections["unattended"] = (
        digest([row.finding for row in combined.unattended]),
        "## unattended linked work\n" + (
            "\n".join(row.finding for row in combined.unattended) or "none"
        ),
    )
    levels = []
    seen_levels = []
    names = {key: value for report in reports for key, value in report.machine_names}
    for report in reports:
        if report.levels is not None and report.levels not in seen_levels:
            seen_levels.append(report.levels)
            levels.extend(level_readout_lines(report.levels, machine_names=names))
    sections["machines:" + ",".join(str(key) for key in sorted({r.project_id for r in reports}))] = (
        digest(_age_blind([
            {**{key: report_dict(report).get(key) for key in _SHARED_FACTS},
             "native_models": [asdict(row) for row in report.native_models],
             "machine_names": report.machine_names} for report in reports
        ])),
        "\n".join([*machine_shared_lines(reports, now=combined.composed_at), *levels]),
    )
    return sections


def report_read_delta(
    conn: Any, *, session_id: str, combined: CombinedFleetReport, full: bool = False,
) -> str:
    """Advance only the served sections; project-filtered reads preserve others."""
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    lock = " FOR UPDATE" if db_backend.connection_is_postgres(conn) else ""
    row = conn.execute(
        f"SELECT {READ_FINGERPRINTS_COLUMN} FROM harness_sessions "
        f"WHERE session_id = {marker}{lock}", (session_id,),
    ).fetchone()
    raw = dict(row).get(READ_FINGERPRINTS_COLUMN) if row else None
    try:
        prior = json.loads(raw) if raw else {}
        if not isinstance(prior, dict):
            raise ValueError("read checkpoints must be an object")
    except (ValueError, TypeError) as exc:
        if not full:
            raise ValueError(
                "steering_report_read_state_invalid: reset the read checkpoint "
                "with `yoke steering report get --full`"
            ) from exc
        prior = {}
    sections = _sections(combined)
    changed = [body for key, (fingerprint, body) in sections.items()
               if prior.get(key) != fingerprint]
    unchanged = len(sections) - len(changed)
    prior.update({key: fingerprint for key, (fingerprint, _) in sections.items()})
    conn.execute(
        f"UPDATE harness_sessions SET {READ_FINGERPRINTS_COLUMN} = {marker} "
        f"WHERE session_id = {marker}",
        (json.dumps(prior, sort_keys=True, separators=(",", ":")), session_id),
    )
    conn.commit()
    return "\n\n".join([
        *([COMBINED_PREAMBLE] if changed else []), *changed,
        f"steering report: {unchanged} section(s) unchanged; --full for all.",
    ])


__all__ = ["READ_FINGERPRINTS_COLUMN", "READ_FINGERPRINTS_DDL", "report_read_delta"]
