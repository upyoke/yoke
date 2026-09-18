"""Render the Markdown health report from a ``doctor.run.run`` result.

The engine entrypoint holds live :class:`CheckResult` records and formats
straight from them. Every other runner receives the same verdicts as a
transported result payload — a relayed batch, an in-process dispatch —
and needs the identical report, so the payload is rebuilt into a
collector here rather than each caller inventing its own layout.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from yoke_core.engines.doctor_report import RecordCollector


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
    return rec.format_report()


__all__ = ["report_from_result"]
