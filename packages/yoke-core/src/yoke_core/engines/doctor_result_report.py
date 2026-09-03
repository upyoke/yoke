"""Render the Markdown health report from a ``doctor.run.run`` result.

The engine entrypoint holds live :class:`CheckResult` records and formats
straight from them. Every other runner receives the same verdicts as a
transported result payload — a relayed batch, an in-process dispatch —
and needs the identical report, so the payload is rebuilt into a
collector here rather than each caller inventing its own layout.

The remediation footer lives here too: it is applied at the moment a
report is rendered, so both entrances attach it the same way.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from yoke_contracts.field_note_text import FOOTER as _FIELD_NOTE_FOOTER
from yoke_core.engines.doctor_report import RecordCollector


def remediation_with_footer(prompt_text: str) -> str:
    """Append the field-note footer to one HC's remediation prompt.

    Idempotent: re-wrapping text that already carries the footer is a
    no-op. Every FAIL / WARN remediation prompt in the Markdown report
    surfaces the footer so the operator-facing channel for the Ouroboros
    learning loop is one screen away when doctor finds work.
    """
    if _FIELD_NOTE_FOOTER in prompt_text:
        return prompt_text
    return f"{prompt_text}\n\n{_FIELD_NOTE_FOOTER}"


def attach_remediation_footers(rec: RecordCollector) -> None:
    """Wrap each FAIL / WARN result's ``detail`` with the field-note
    footer before report rendering. Applied at the doctor result-render
    layer so per-HC modules need no edits."""
    for r in rec.results:
        if r.result in ("FAIL", "WARN"):
            r.detail = remediation_with_footer(r.detail)


def _collector_from_rows(rows: Iterable[Mapping[str, Any]]) -> RecordCollector:
    """Rebuild a collector from transported result rows."""
    rec = RecordCollector()
    for row in rows:
        rec.record(
            str(row.get("hc") or ""),
            str(row.get("name") or ""),
            str(row.get("severity") or ""),
            str(row.get("detail") or ""),
        )
    return rec


def report_from_result(result: Mapping[str, Any]) -> str:
    """The Markdown health report for one ``doctor.run.run`` result."""
    rec = _collector_from_rows(result.get("results") or [])
    attach_remediation_footers(rec)
    return rec.format_report()


__all__ = [
    "attach_remediation_footers",
    "remediation_with_footer",
    "report_from_result",
]
