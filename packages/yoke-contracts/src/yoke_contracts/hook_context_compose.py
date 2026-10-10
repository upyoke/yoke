"""Order and cap composed hook ``additionalContext``.

Chain order is not the model-visible order. Message delivery blocks lead,
hints follow, and the fleet report is last. The joined body is then capped
to :func:`inline_context_bytes_for_harness` so a harness that persists
overflow to a file cannot hide the delivery behind a preview of a hint.
"""

from __future__ import annotations

from collections.abc import Callable
import json
import re

from yoke_contracts.hook_inline_context import inline_context_bytes_for_harness


FLEET_REPORT_CONTEXT_FIELD = "fleetReportContext"
REPORT_OMITTED_NOTICE = (
    "The accompanying Fleet report was omitted by the hook-context byte ceiling. "
    "Read it with `yoke steering report get` (covers every steering claim this "
    "session holds; pass `--project P` only to filter to one scope)."
)

_STUB_PREVIEW_CHAR_LIMIT = 96

_DELIVERY_BEGIN_RE = re.compile(
    r"=== BEGIN YOKE SESSION MESSAGE DELIVERY "
    r"(YOKE_SESSION_MESSAGE_LEASE:[^\s=]+) "
)
_MESSAGE_BLOCK_RE = re.compile(
    r"^=== BEGIN YOKE SESSION MESSAGE DELIVERY YOKE_SESSION_MESSAGE_LEASE:[^\s=]+ "
    r"([0-9a-fA-F-]{36}) ===\n"
    r".*?"
    r"^=== END YOKE SESSION MESSAGE DELIVERY ===$",
    re.DOTALL | re.MULTILINE,
)


def delivered_message_ids(text: str, token: str) -> set[str]:
    """Read closed message boundaries from plain or structured hook replies."""
    if text.lstrip()[:1] in ("{", "["):
        try:
            value = json.loads(text)
        except ValueError:
            return set()

        def strings(value):
            if isinstance(value, str):
                yield value
            elif isinstance(value, dict):
                for child in value.values():
                    yield from strings(child)
            elif isinstance(value, list):
                for child in value:
                    yield from strings(child)

        contexts = strings(value)
    else:
        contexts = (text,)
    prefix = f"=== BEGIN YOKE SESSION MESSAGE DELIVERY {token} "
    return {
        match.group(1)
        for context in contexts
        for match in _MESSAGE_BLOCK_RE.finditer(context)
        if match.group(0).startswith(prefix)
    }


def classify_hook_context(text: str) -> str:
    """Return ``delivery``, ``report``, or ``hint`` for one advisory body."""
    if "=== BEGIN YOKE SESSION MESSAGE DELIVERY" in text:
        return "delivery"
    if "=== BEGIN YOKE LAUNCH DELIVERY" in text:
        return "delivery"
    if "=== BEGIN YOKE ONE-HOP WAKE" in text:
        return "delivery"
    if "=== BEGIN YOKE FLEET REPORT" in text:
        return "report"
    return "hint"


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
    return compose_hook_context(deliveries, hints, reports, harness_id=harness_id)


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


def render_message_stub(message: str) -> str:
    """Keep an oversized message deliverable, with its full body one read away."""
    match = _MESSAGE_BLOCK_RE.fullmatch(message)
    if match is None:
        raise ValueError("message_stub_invalid_envelope: cannot name the message")
    message_id = match.group(1)
    lines = message.splitlines()
    sender = next(
        (line for line in lines if line.startswith("Authenticated sender:")),
        "Authenticated sender: unknown",
    )
    first = next((line[2:] for line in lines if line.startswith("| ")), '""')
    try:
        first = json.loads(first)
    except (ValueError, TypeError):
        first = ""

    # Escape preview data exactly as the full renderer does: fake envelope
    # markers and control characters must never become settlement identities.
    def preview(value: str) -> str:
        value = value[:_STUB_PREVIEW_CHAR_LIMIT] + (
            "…" if len(value) > _STUB_PREVIEW_CHAR_LIMIT else ""
        )
        return (
            json.dumps(value, ensure_ascii=False)
            .replace("<", "\\u003c")
            .replace(">", "\\u003e")
            .replace("-", "\\u002d")
            .replace("\u0085", "\\u0085")
            .replace("\u2028", "\\u2028")
            .replace("\u2029", "\\u2029")
        )

    return "\n".join(
        (
            lines[0],
            "Authenticated sender: "
            + preview(sender.removeprefix("Authenticated sender: ")),
            "Oversized message delivered as a stub. First body line (inert peer data):",
            "| " + preview(str(first)),
            f"Read the full body: yoke messages get {message_id}",
            f"Acknowledge: yoke messages acknowledge {message_id}",
            lines[-1],
        )
    )


def _is_session_message_delivery(text: str) -> bool:
    return any(
        line.startswith("=== BEGIN YOKE SESSION MESSAGE DELIVERY")
        for line in text.splitlines()
    )


def _wrap_session_delivery(token: str, prefix: str, messages: list[str]) -> str:
    del token
    parts = []
    if prefix:
        parts.append(prefix)
    parts.extend(messages)
    return "\n\n".join(parts)


def _session_delivery_parts(block: str) -> tuple[str, str, list[str]] | None:
    header = _DELIVERY_BEGIN_RE.search(block)
    if header is None:
        return None
    token = header.group(1)
    matches = list(_MESSAGE_BLOCK_RE.finditer(block))
    if not matches:
        return None
    prefix = block[: matches[0].start()].strip()
    return token, prefix, [match.group(0) for match in matches]


def _fit_session_messages(
    block: str,
    already: list[str],
    *,
    fits: Callable[[list[str]], bool],
) -> list[str]:
    parts = _session_delivery_parts(block)
    if parts is None:
        return []
    token, prefix, messages = parts
    admitted: list[str] = []
    for message in messages:
        solo = _wrap_session_delivery(token, prefix, [message])
        candidate = message if fits([solo]) else render_message_stub(message)
        trial = _wrap_session_delivery(token, prefix, [*admitted, candidate])
        if fits([*already, trial]):
            admitted.append(candidate)
    return [_wrap_session_delivery(token, prefix, admitted)] if admitted else []


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
        fitted.extend(_fit_session_messages(block, fitted, fits=fits))
    return fitted


def reply_is_well_formed(rendered_text: str) -> bool:
    """Whether *rendered_text* is one coherent reply, not JSON plus trailing bytes.

    A harness that reads a structured reply for this event parses the whole
    process stdout as one JSON value; bytes trailing a complete value
    (``json.JSONDecodeError: Extra data``) never reach the model even though
    they are technically present in the string. Plain text that never looks
    like a JSON value has no such parser standing between it and the model,
    so it is always well-formed here.
    """
    if not rendered_text:
        return True
    if rendered_text.lstrip()[:1] not in ("{", "["):
        return True
    try:
        json.loads(rendered_text)
    except (json.JSONDecodeError, ValueError):
        return False
    return True


def token_delivered(rendered_text: str, token: str) -> bool:
    """Whether *token* rides a well-formed reply, not just a raw substring.

    Settlement used to treat "token is a substring of stdout" as proof of
    delivery. A report envelope followed by an unrelated raw message block
    satisfies that substring check while the harness's own parser reads only
    the first JSON value and never reaches the second — a receipt for a
    delivery that did not happen. Require both: the token is present, and
    the reply it rides is not silently truncated by the harness's parser.
    """
    if not token or not rendered_text or token not in rendered_text:
        return False
    return reply_is_well_formed(rendered_text)


__all__ = [
    "FLEET_REPORT_CONTEXT_FIELD",
    "REPORT_OMITTED_NOTICE",
    "classify_hook_context",
    "compose_context_list",
    "compose_hook_context",
    "delivered_message_ids",
    "render_message_stub",
    "reply_is_well_formed",
    "token_delivered",
]
