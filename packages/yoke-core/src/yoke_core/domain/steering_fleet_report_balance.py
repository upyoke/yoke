"""Model-aware launch-balance rendering for steering fleet reports."""

from __future__ import annotations

from collections import defaultdict
from typing import Iterable, Protocol

from yoke_core.domain.machine_registry import display_name
from yoke_core.domain.steering_fleet_report_capacity import (
    SessionCount,
    capacity_line,
)


LAUNCH_BALANCE_NOTE = (
    "allocate by headroom: keep one session on every surface above 100% so "
    "each harness stays exercised, then send the rest to the surface with the "
    "most headroom and run it down; level counts only when headrooms are "
    "comparable; no per-surface session cap"
)


class BalanceReport(Protocol):
    launchable: tuple[object, ...]
    session_counts: tuple[SessionCount, ...]
    machine_capacity: tuple[object, ...]
    origin_counts: tuple[tuple[str, int], ...]
    machine_names: tuple[tuple[str, str], ...]


def context_label(value: int | None) -> str:
    if value is None:
        return "unknown"
    if value % 1_000_000 == 0:
        return f"{value // 1_000_000}m"
    if value % 1_000 == 0:
        return f"{value // 1_000}k"
    return str(value)


def _fact(served: object, requested: object, formatter=str) -> str:
    if served is not None:
        rendered = formatter(served)
        if requested is not None and requested != served:
            return f"{rendered} (requested {formatter(requested)})"
        return rendered
    if requested is not None:
        return f"{formatter(requested)} (requested)"
    return "unknown"


def session_selection_label(row: SessionCount) -> str:
    model = _fact(row.model, row.requested_model)
    effort = _fact(row.reasoning_effort, row.requested_reasoning_effort)
    context = _fact(
        row.context_window_tokens,
        row.requested_context_window_tokens,
        context_label,
    )
    return f"{model} · effort {effort} · context {context}"


def selection_labels(
    counts: Iterable[SessionCount],
    *,
    machine_id: str,
    surface: str,
) -> tuple[str, ...]:
    return tuple(
        sorted(
            f"{session_selection_label(row)} ×{row.count}"
            for row in counts
            if row.machine_id == machine_id and row.surface == surface
        )
    )


def aggregate_session_counts(
    reports: Iterable[BalanceReport],
) -> tuple[SessionCount, ...]:
    grouped: dict[tuple[object, ...], int] = defaultdict(int)
    samples: dict[tuple[object, ...], SessionCount] = {}
    for report in reports:
        for row in report.session_counts:
            key = (
                row.machine_id,
                row.surface,
                row.requested_model,
                row.requested_reasoning_effort,
                row.requested_context_window_tokens,
                row.model,
                row.reasoning_effort,
                row.context_window_tokens,
            )
            grouped[key] += row.count
            samples[key] = row
    return tuple(
        SessionCount(
            machine_id=sample.machine_id,
            surface=sample.surface,
            count=grouped[key],
            requested_model=sample.requested_model,
            requested_reasoning_effort=sample.requested_reasoning_effort,
            requested_context_window_tokens=sample.requested_context_window_tokens,
            model=sample.model,
            reasoning_effort=sample.reasoning_effort,
            context_window_tokens=sample.context_window_tokens,
        )
        for key, sample in sorted(samples.items(), key=lambda item: str(item[0]))
    )


def selection_fingerprint_rows(
    counts: Iterable[SessionCount],
) -> list[tuple[object, ...]]:
    """Return deterministic requested-and-served selection identity rows."""
    return sorted(
        (
            row.machine_id,
            row.surface,
            row.count,
            row.requested_model,
            row.requested_reasoning_effort,
            row.requested_context_window_tokens,
            row.model,
            row.reasoning_effort,
            row.context_window_tokens,
        )
        for row in counts
    )


def launch_balance_lines(report: BalanceReport, *, note: bool) -> list[str]:
    totals: dict[tuple[str, str], int] = defaultdict(int)
    for row in report.session_counts:
        totals[(row.machine_id, row.surface)] += row.count
    by_machine: dict[str, list[str]] = defaultdict(list)
    for ready in report.launchable:
        machine = str(getattr(ready, "machine_id"))
        surface = str(getattr(ready, "surface"))
        selections = selection_labels(
            report.session_counts,
            machine_id=machine,
            surface=surface,
        )
        detail = f" [{'; '.join(selections)}]" if selections else ""
        by_machine[machine].append(f"{surface} {totals[(machine, surface)]}{detail}")
    capacity = {
        str(getattr(entry, "machine_id")): entry
        for entry in getattr(report, "machine_capacity", ())
    }
    machine_ids = set(by_machine)
    if note:
        machine_ids.update(capacity)
    names = dict(report.machine_names)
    lines: list[str] = []
    for machine in sorted(machine_ids, key=lambda item: display_name(names, item)):
        lines.append(f"launch balance  {display_name(names, machine)}")
        lines.append(
            f"  {' · '.join(sorted(by_machine[machine])) or 'no launchable surface'}"
        )
        if note and machine in capacity:
            lines.append(f"  {capacity_line(capacity[machine])}")
        if note:
            lines.append(f"  {LAUNCH_BALANCE_NOTE}")
    if report.origin_counts:
        lines.append(
            "origin "
            + " · ".join(f"{name} {count}" for name, count in report.origin_counts)
        )
    return lines


__all__ = [
    "LAUNCH_BALANCE_NOTE",
    "aggregate_session_counts",
    "context_label",
    "launch_balance_lines",
    "selection_fingerprint_rows",
    "selection_labels",
    "session_selection_label",
]
