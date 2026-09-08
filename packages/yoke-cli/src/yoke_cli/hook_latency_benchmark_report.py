"""Pure report parsing and comparison for the hook latency benchmark."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence

from yoke_contracts.hook_evaluator_protocol import HOOK_CALL_IDENTITY_FIELD


# The dispatch row each sample phase is joined to, keyed by the sample field
# that holds it. One tool call emits one row per hook event.
PHASE_HOOK_EVENTS = {"pre_phase": "PreToolUse", "post_phase": "PostToolUse"}


class BenchmarkRefusal(RuntimeError):
    def __init__(self, code: str, detail: str, recovery: str) -> None:
        self.code = code
        self.detail = detail
        self.recovery = recovery
        super().__init__(f"{code}: {detail}; recovery: {recovery}")


def parse_provenance(stderr: str) -> dict[str, str | None]:
    line = next(
        (line for line in reversed(stderr.splitlines()) if "yoke-provenance " in line),
        "",
    )
    client = re.search(r"\bclient sha=(\S+)", line)
    server = re.search(r"\bserver sha=(\S+)", line)
    return {
        "client_revision": client.group(1) if client else None,
        "server_revision": server.group(1) if server else None,
    }


def _mean(values: list[int]) -> int | None:
    return int(round(sum(values) / len(values))) if values else None


def summarize_samples(samples: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    direct_fields = ("pre_hook_ms", "command_ms", "post_hook_ms", "envelope_ms")
    summary = {
        f"{field}_mean": _mean(
            [
                int(sample[field])
                for sample in samples
                if isinstance(sample.get(field), int)
            ]
        )
        for field in direct_fields
    }
    phases = [
        sample.get(name)
        for sample in samples
        for name in PHASE_HOOK_EVENTS
        if isinstance(sample.get(name), dict)
    ]
    hook_total = len(samples) * len(PHASE_HOOK_EVENTS)
    evaluator_timed = sum(
        1 for phase in phases if isinstance(phase.get("evaluator_ms"), int)
    )
    client_timed = sum(
        1 for phase in phases if isinstance(phase.get("client_wall_ms"), int)
    )
    summary.update(
        {
            "direct_timed_count": sum(
                1
                for sample in samples
                for field in direct_fields
                if isinstance(sample.get(field), int)
            ),
            "direct_total_count": len(samples) * len(direct_fields),
            "phase_record_count": len(phases),
            "phase_total_count": hook_total,
            "evaluator_timed_count": evaluator_timed,
            "evaluator_timing_coverage_pct": (
                round(evaluator_timed * 100.0 / hook_total, 1) if hook_total else 0.0
            ),
            "client_wall_timed_count": client_timed,
            "client_wall_timing_coverage_pct": (
                round(client_timed * 100.0 / hook_total, 1) if hook_total else 0.0
            ),
        }
    )
    return summary


def compare_reports(
    current: Mapping[str, Any], baseline: Mapping[str, Any]
) -> dict[str, Any]:
    reasons = []
    for field in (
        "harness",
        "surface",
        "client_revision",
        "server_revision",
        "command",
        "run_count",
    ):
        if current.get(field) != baseline.get(field):
            reasons.append(f"{field} differs")
    for label, report in (("current", current), ("baseline", baseline)):
        summary = report.get("summary") or {}
        for phase, field in (
            ("evaluator", "evaluator_timing_coverage_pct"),
            ("client-wall", "client_wall_timing_coverage_pct"),
        ):
            coverage = summary.get(field)
            if coverage != 100.0:
                reasons.append(f"{label} {phase} timing coverage is {coverage}%")
    deltas = {}
    for field in (
        "pre_hook_ms_mean",
        "command_ms_mean",
        "post_hook_ms_mean",
        "envelope_ms_mean",
    ):
        now_value = (current.get("summary") or {}).get(field)
        before_value = (baseline.get("summary") or {}).get(field)
        deltas[field] = (
            now_value - before_value
            if isinstance(now_value, int) and isinstance(before_value, int)
            else None
        )
    return {
        "status": "comparable" if not reasons else "incomparable",
        "reasons": reasons,
        "mean_delta_ms": deltas,
    }


def _event_envelope(row: Mapping[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(row.get("envelope") or "{}")
    except (AttributeError, TypeError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def _event_phase(row: Mapping[str, Any]) -> dict[str, Any]:
    envelope = _event_envelope(row)
    context = envelope.get("context", {})
    if not isinstance(context, dict):
        context = {}

    def duration(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return parsed if parsed >= 0 else None

    evaluator_ms = duration(row.get("duration_ms"))
    if evaluator_ms is None:
        evaluator_ms = duration(envelope.get("duration_ms"))
    client_wall_ms = duration(context.get("client_wall_ms"))
    return {
        "evaluator_ms": evaluator_ms,
        "client_wall_ms": client_wall_ms,
        "client_unattributed_ms": (
            max(0, client_wall_ms - evaluator_ms)
            if client_wall_ms is not None and evaluator_ms is not None
            else None
        ),
        "evaluator": context.get("evaluator"),
        "resident_warm_duration_ms": duration(context.get("resident_warm_duration_ms")),
        "fallback_reason": context.get("evaluator_fallback_reason"),
    }


def _row_call_identity(row: Mapping[str, Any]) -> tuple[str, str]:
    """The ``(call identity, hook event)`` a dispatch row names, or blanks."""
    envelope = _event_envelope(row)
    context = envelope.get("context")
    identity = (
        context.get(HOOK_CALL_IDENTITY_FIELD) if isinstance(context, dict) else None
    )
    return (
        str(identity) if isinstance(identity, str) else "",
        str(envelope.get("hook_event_name") or ""),
    )


def attach_durable_phases(
    samples: list[dict[str, Any]], rows: Sequence[Mapping[str, Any]]
) -> None:
    """Attach each dispatch row to the sample whose call identity it names.

    Arrival order carries no meaning here: the session that ran the
    benchmark also ran its own unrelated hooks, and a resident evaluator
    delivers its telemetry in bounded batches afterwards, so the rows for
    one sample can be interleaved, reordered, or still in flight. Each
    phase is attached on its own identity, and one that has no row stays
    ``None`` so the caller reports it missing rather than borrowing a
    neighbour's timing.
    """
    by_identity: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in sorted(rows, key=lambda row: int(row.get("id") or 0)):
        key = _row_call_identity(row)
        if key[0] and key[1]:
            by_identity.setdefault(key, row)
    for sample in samples:
        identity = str(sample.get(HOOK_CALL_IDENTITY_FIELD) or "")
        for field, event in PHASE_HOOK_EVENTS.items():
            row = by_identity.get((identity, event))
            sample[field] = _event_phase(row) if row is not None else None


def phase_coverage(
    samples: Sequence[Mapping[str, Any]],
    *,
    dispatch_row_count: int,
    dispatch_row_limit: int,
) -> dict[str, Any]:
    """Name every phase with no durable row instead of implying zero."""
    truncated = dispatch_row_count >= dispatch_row_limit
    missing = [
        {
            "ordinal": sample.get("ordinal"),
            "phase": field,
            "hook_event": event,
            "reason": (
                "no HookDispatchTelemetry row names this call identity; the "
                "bounded query returned its full row limit, so the row may be "
                "outside it"
                if truncated
                else "no HookDispatchTelemetry row names this call identity"
            ),
        }
        for sample in samples
        for field, event in PHASE_HOOK_EVENTS.items()
        if not isinstance(sample.get(field), dict)
    ]
    return {
        "dispatch_row_count": dispatch_row_count,
        "dispatch_row_limit": dispatch_row_limit,
        "dispatch_row_limit_reached": truncated,
        "missing_phases": missing,
    }


def load_report(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise BenchmarkRefusal(
            "HOOK_BENCHMARK_BASELINE_INVALID",
            f"could not read baseline {path} ({type(exc).__name__})",
            "provide JSON emitted by `yoke hook benchmark --json`",
        ) from None
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise BenchmarkRefusal(
            "HOOK_BENCHMARK_BASELINE_INVALID",
            "baseline is not a schema-1 hook benchmark report",
            "provide JSON emitted by `yoke hook benchmark --json`",
        )
    return value


__all__ = [
    "BenchmarkRefusal",
    "PHASE_HOOK_EVENTS",
    "attach_durable_phases",
    "compare_reports",
    "load_report",
    "parse_provenance",
    "phase_coverage",
    "summarize_samples",
]
