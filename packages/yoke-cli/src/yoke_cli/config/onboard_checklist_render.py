"""Renderers for onboarding checklist records."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from yoke_cli.config.onboard_checklist_schema import (
    SCHEMA_VERSION,
)

DEFAULT_VIEW_PATH = ".yoke/onboarding/CHECKLIST.md"


def dumps_json(report: Mapping[str, Any]) -> str:
    return json.dumps(report, indent=2, sort_keys=True) + "\n"


def render_human(report: Mapping[str, Any]) -> str:
    run = _run_payload(report)
    summary = _summary_payload(run)
    doctor_status = _doctor_status(run)
    lines = [
        "Yoke onboarding checklist",
        f"  run: {run['run_id']}",
        f"  branch: {run['branch']}",
    ]
    if report.get("record_path"):
        lines.append(f"  record: {report['record_path']}")
    if report.get("view_path"):
        lines.append(f"  view: {report['view_path']}")
    lines.extend([
        f"  schema_version: {SCHEMA_VERSION}",
        f"  doctor: {doctor_status}",
        "",
        "Rows:",
    ])
    for row in run["rows"]:
        lines.append(
            f"  - {row['step']} {row['row_id']}: {row['status']}"
            f" ({row['owner']})"
        )
    lines.extend([
        "",
        "Summary:",
        f"  open_rows: {_summary_count(summary, 'open')}",
        f"  blocked_rows: {_summary_count(summary, 'blocked')}",
        "",
    ])
    return "\n".join(lines)


def render_markdown(record: Mapping[str, Any]) -> str:
    rows = record["rows"]
    doctor_status = _doctor_status(record)
    lines = [
        "# Yoke Onboarding Checklist",
        "",
        f"- Run: `{record['run_id']}`",
        f"- Branch: `{record['branch']}`",
        f"- Doctor status: `{doctor_status}`",
        "",
        "| Step | Row | Status | Layer | Owner | Evidence / Blocker |",
        "|---:|---|---|---|---|---|",
    ]
    for row in rows:
        detail = row.get("blocker") or row.get("evidence") or row.get("note") or ""
        lines.append(
            f"| {row['step']} | `{row['row_id']}` | {row['status']} | "
            f"{row['layer']} | {row['owner']} | {_escape_table(str(detail))} |"
        )
    lines.extend([
        "",
        "## Handoff",
        "",
        "Resume with:",
        "",
        f"```bash\nyoke onboard checklist --run-id {record['run_id']}\n```",
        "",
    ])
    return "\n".join(lines)


def _escape_table(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def resolve_view_path(
    project_root: str | Path | None,
    view_path: str | Path | None,
) -> Path | None:
    if view_path is not None:
        selected = Path(view_path).expanduser()
        if selected.is_absolute():
            return selected
        if project_root is None:
            raise ValueError("--view-path must be absolute without --project-root")
        return Path(project_root).expanduser() / selected
    if project_root is None:
        return None
    return Path(project_root).expanduser() / DEFAULT_VIEW_PATH


def _run_payload(report: Mapping[str, Any]) -> Mapping[str, Any]:
    run = report.get("run")
    return run if isinstance(run, Mapping) else report


def _summary_payload(run: Mapping[str, Any]) -> Mapping[str, Any]:
    summary = run.get("summary")
    return summary if isinstance(summary, Mapping) else {}


def _doctor_status(run: Mapping[str, Any]) -> str:
    doctor = run.get("doctor")
    if isinstance(doctor, Mapping) and doctor.get("status"):
        return str(doctor["status"])
    summary = _summary_payload(run)
    return str(summary.get("status") or run.get("status") or "unknown")


def _summary_count(summary: Mapping[str, Any], kind: str) -> int:
    count_key = f"{kind}_row_count"
    if count_key in summary:
        return int(summary[count_key] or 0)
    rows_key = f"{kind}_rows"
    rows = summary.get(rows_key)
    return len(rows) if isinstance(rows, list) else 0


__all__ = [
    "DEFAULT_VIEW_PATH",
    "dumps_json",
    "render_human",
    "render_markdown",
    "resolve_view_path",
]
