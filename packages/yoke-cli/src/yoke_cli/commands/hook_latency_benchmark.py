"""Client-local ``yoke hook benchmark`` command."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Dict, List, Tuple

from yoke_contracts.field_note_text import FOOTER as _FIELD_NOTE_FOOTER


HOOK_BENCHMARK_USAGE = (
    "yoke hook benchmark [--samples N] [--compare REPORT.json] [--json]"
)


def _human(report: dict) -> None:
    summary = report["summary"]
    evidence = report["concurrency_evidence"]
    sys.stdout.write(
        "HOOK LATENCY BENCHMARK (milliseconds)\n"
        f"Harness: {report['harness']}  Surface: {report['surface']}  "
        f"Runs: {report['run_count']}  Status: {report['status']}\n"
        f"Window: {report['time_window']['started_at']} -> "
        f"{report['time_window']['ended_at']}\n"
        f"Revisions: client={report['client_revision'] or 'unreported'} "
        f"server={report['server_revision'] or 'unreported'}\n"
        f"Means: pre={summary['pre_hook_ms_mean']} command={summary['command_ms_mean']} "
        f"post={summary['post_hook_ms_mean']} envelope={summary['envelope_ms_mean']}\n"
        f"Evaluator timing coverage: {summary['evaluator_timed_count']}/"
        f"{summary['phase_total_count']} "
        f"({summary['evaluator_timing_coverage_pct']:.1f}%)\n"
        f"Client-wall timing coverage: {summary['client_wall_timed_count']}/"
        f"{summary['phase_total_count']} "
        f"({summary['client_wall_timing_coverage_pct']:.1f}%)\n"
        "Concurrency evidence: "
        f"live roster {evidence['start']['live_roster_count']} -> "
        f"{evidence['end']['live_roster_count']}; running-session proxy "
        f"{evidence['start']['tool_active_bucket_proxy_count']} -> "
        f"{evidence['end']['tool_active_bucket_proxy_count']}\n"
        f"Definition: {evidence['definition']}\n"
    )
    coverage = report["phase_coverage"]
    for missing in coverage["missing_phases"]:
        sys.stdout.write(
            f"Missing phase: sample {missing['ordinal']} "
            f"{missing['hook_event']} — {missing['reason']}\n"
        )
    if coverage["dispatch_row_limit_reached"]:
        sys.stdout.write(
            "Dispatch rows returned the full bounded limit "
            f"({coverage['dispatch_row_limit']}); rerun with fewer samples or "
            "from a quieter session to widen the window this run can see.\n"
        )
    comparison = report.get("comparison")
    if comparison:
        sys.stdout.write(
            f"Comparison: {comparison['status']}"
            + (
                f" ({'; '.join(comparison['reasons'])})"
                if comparison["reasons"]
                else ""
            )
            + "\n"
        )
        for field, value in comparison["mean_delta_ms"].items():
            sys.stdout.write(
                f"  {field}: {value:+d} ms\n"
                if value is not None
                else f"  {field}: unavailable\n"
            )


def hook_latency_benchmark(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke hook benchmark",
        description=(
            "Run a fixed harmless command through normal PreToolUse and "
            "PostToolUse checks. This is on demand only and generates no load."
        ),
        epilog=_FIELD_NOTE_FOOTER,
    )
    parser.add_argument("--samples", type=int, default=5)
    parser.add_argument("--compare", type=Path)
    parser.add_argument("--json", action="store_true", dest="json_mode")
    parsed = parser.parse_args(args)

    from yoke_cli.hook_latency_benchmark import (
        BenchmarkRefusal,
        compare_reports,
        load_report,
        run_benchmark,
    )

    try:
        report = run_benchmark(parsed.samples)
        if parsed.compare is not None:
            report["comparison"] = compare_reports(report, load_report(parsed.compare))
    except BenchmarkRefusal as refusal:
        sys.stderr.write(
            f"ERROR: {refusal.code}: {refusal.detail}; recovery: {refusal.recovery}\n"
        )
        return 1
    if parsed.json_mode:
        sys.stdout.write(json.dumps(report, sort_keys=True) + "\n")
    else:
        _human(report)
    return 0


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], Callable[[List[str]], int]] = {
    ("hook", "benchmark"): hook_latency_benchmark,
}
TOOL_SHAPED_USAGE = {"yoke hook benchmark": HOOK_BENCHMARK_USAGE}


__all__ = [
    "HOOK_BENCHMARK_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "hook_latency_benchmark",
]
