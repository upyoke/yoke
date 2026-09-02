"""Order and cap composed hook ``additionalContext``.

Chain order is not the model-visible order. Message delivery blocks lead,
hints follow, and the fleet report is last. The joined body is then capped
to :func:`inline_context_bytes_for_harness` so a harness that persists
overflow to a file cannot hide the delivery behind a preview of a hint.
"""

from __future__ import annotations

from collections.abc import Callable
import re

from yoke_contracts.hook_inline_context import inline_context_bytes_for_harness


FLEET_REPORT_CONTEXT_FIELD = "fleetReportContext"
OVERFLOW_LEASE_PREFIX = "overflow-lease:"
POINTER_BEGIN = "=== BEGIN YOKE SESSION MESSAGE DELIVERY POINTER ==="
POINTER_END = "=== END YOKE SESSION MESSAGE DELIVERY POINTER ==="
REPORT_OMITTED_NOTICE = (
    "The accompanying Fleet report was omitted by the hook-context byte ceiling. "
    "Read it with `yoke steering report get` (covers every steering claim this "
    "session holds; pass `--project P` only to filter to one scope)."
)

_LEASE_RE = re.compile(r"YOKE_SESSION_MESSAGE_LEASE:([^\s=]+)")
_MESSAGE_RE = re.compile(
    r"--- BEGIN YOKE SESSION MESSAGE ([0-9a-fA-F-]{36}) ---"
)


def classify_hook_context(text: str) -> str:
    """Return ``delivery``, ``report``, or ``hint`` for one advisory body."""
    if POINTER_BEGIN in text:
        return "delivery"
    if "=== BEGIN YOKE SESSION MESSAGE DELIVERY" in text:
        return "delivery"
    if "=== BEGIN YOKE LAUNCH DELIVERY" in text:
        return "delivery"
    if "=== BEGIN YOKE ONE-HOP WAKE" in text:
        return "delivery"
    if "=== BEGIN YOKE FLEET REPORT" in text:
        return "report"
    return "hint"


def overflow_lease_marker(lease_id: str) -> str:
    """Settlement token that is not the injected-lease string."""
    return f"{OVERFLOW_LEASE_PREFIX}{lease_id}"


def compose_context_list(contexts: list[str], *, harness_id: str) -> str:
    """Classify, reorder, and cap a list of already-rendered advisory bodies."""
    deliveries: list[str] = []
    hints: list[str] = []
    reports: list[str] = []
    for raw in contexts:
        if not isinstance(raw, str) or not raw.strip():
            continue
        kind = classify_hook_context(raw)
        if kind == "delivery":
            deliveries.append(raw)
        elif kind == "report":
            reports.append(raw)
        else:
            hints.append(raw)
    return compose_hook_context(
        deliveries, hints, reports, harness_id=harness_id
    )


def compose_hook_context(
    deliveries: list[str],
    hints: list[str],
    reports: list[str],
    *,
    harness_id: str,
) -> str:
    """Join delivery, then hints, then report, under the harness inline cap."""
    budget = inline_context_bytes_for_harness(harness_id)

    def join(parts: list[str]) -> str:
        return "\n\n".join(part for part in parts if part)

    def fits(parts: list[str]) -> bool:
        return len(join(parts).encode("utf-8")) <= budget

    full = [*deliveries, *hints, *reports]
    if fits(full):
        return join(full)
    without_hints = [*deliveries, *reports]
    if fits(without_hints):
        return join(without_hints)
    omitted = REPORT_OMITTED_NOTICE if reports else ""
    with_notice = [*deliveries, omitted] if omitted else list(deliveries)
    if fits(with_notice):
        return join(with_notice)
    if fits(list(deliveries)):
        return join(deliveries)
    fitted = _fit_deliveries(deliveries, fits=fits)
    if omitted and fits([*fitted, omitted]):
        fitted.append(omitted)
    if fitted:
        return join(fitted)
    leftover: list[str] = []
    for block in [*hints, *reports]:
        if fits([*leftover, block]):
            leftover.append(block)
    return join(leftover)


def render_overflow_pointer(block: str) -> str:
    """Short stand-in that names the message without claiming injection."""
    match = _LEASE_RE.search(block)
    lease_id = match.group(1) if match else "unknown"
    message_ids = _MESSAGE_RE.findall(block)
    reads = [
        f"Read: yoke messages get {message_id} --json" for message_id in message_ids
    ] or ["Read: yoke messages get MESSAGE-ID --json"]
    acks = [
        f"Acknowledge: yoke messages acknowledge {message_id}"
        for message_id in message_ids
    ]
    return "\n".join(
        (
            POINTER_BEGIN,
            "Hook context exceeded this harness's inline limit; "
            "the message body was not injected.",
            overflow_lease_marker(lease_id),
            *reads,
            *acks,
            POINTER_END,
        )
    )


def _is_session_message_delivery(text: str) -> bool:
    for line in text.splitlines():
        if line.startswith(POINTER_BEGIN):
            return False
        if line.startswith("=== BEGIN YOKE SESSION MESSAGE DELIVERY"):
            return True
    return False


def _fit_deliveries(
    deliveries: list[str],
    *,
    fits: Callable[[list[str]], bool],
) -> list[str]:
    fitted: list[str] = []
    for block in deliveries:
        if fits([*fitted, block]):
            fitted.append(block)
            continue
        if not _is_session_message_delivery(block):
            continue
        pointer = render_overflow_pointer(block)
        if fits([*fitted, pointer]):
            fitted.append(pointer)
        elif not fitted and fits([pointer]):
            fitted.append(pointer)
    return fitted


__all__ = [
    "FLEET_REPORT_CONTEXT_FIELD",
    "OVERFLOW_LEASE_PREFIX",
    "POINTER_BEGIN",
    "POINTER_END",
    "REPORT_OMITTED_NOTICE",
    "classify_hook_context",
    "compose_context_list",
    "compose_hook_context",
    "overflow_lease_marker",
    "render_overflow_pointer",
]
