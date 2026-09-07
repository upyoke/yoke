"""Pure report parsing and comparison for the hook latency benchmark."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Mapping, Sequence


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
        for name in ("pre_phase", "post_phase")
        if isinstance(sample.get(name), dict)
    ]
    hook_total = len(samples) * 2
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


def attach_durable_phases(
    samples: list[dict[str, Any]], rows: Sequence[Mapping[str, Any]]
) -> None:
    """Attach canonical HookDispatchTelemetry rows without guessing gaps."""
    ordered = sorted(rows, key=lambda row: int(row.get("id") or 0))
    expected = [event for _sample in samples for event in ("PreToolUse", "PostToolUse")]
    observed = [
        str(_event_envelope(row).get("hook_event_name") or "") for row in ordered
    ]
    if observed != expected:
        return
    for index, sample in enumerate(samples):
        sample["pre_phase"] = _event_phase(ordered[index * 2])
        sample["post_phase"] = _event_phase(ordered[index * 2 + 1])


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
    "attach_durable_phases",
    "compare_reports",
    "load_report",
    "parse_provenance",
    "summarize_samples",
]
