"""Fold a finished Cursor native's print-mode result into session totals.

Cursor states a turn's tokens in exactly one machine-readable place for a
relay-run turn: the ``--print --output-format json`` result object the
native writes to stdout as it exits. That object arrives after the last
hook of the turn has already run, so no hook can carry it — the reading
has to be taken from the native's own settled capture, on the machine
that holds it.

Two properties make taking it there safe. A result is one JSON object, so
a capture flushed while the native was still writing does not parse and
folds nothing rather than folding half a turn; the next read, after the
exit status lands, sees the whole object. And the fold routes through the
ordinary Cursor attestation, whose ``request_id`` dedup means re-reading
the same capture on a later poll counts the turn once, however many times
a report is retried.

The result names no model, so the served model is read from the same
conversation store the session's model attestation reads. Naming it is
what lets the shared price reference recognise the tokens; a conversation
whose store names nothing is folded under Cursor's unnamed-model sentinel
rather than under a guess.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.session_usage_facts import usage_document
from yoke_harness.session_relay_native_capture_format import NativeCapture


#: The print-mode envelope a completed turn ends with.
RESULT_TYPE = "result"

#: Cursor's own result-shaped usage keys. All four together are what
#: distinguishes this envelope from any other harness's result object, so
#: a capture written by a different native never folds as Cursor usage.
RESULT_USAGE_FIELDS = (
    "inputTokens",
    "outputTokens",
    "cacheReadTokens",
    "cacheWriteTokens",
)


def native_result_payload(capture: NativeCapture | None) -> dict[str, Any] | None:
    """Return the complete Cursor result object a capture holds, if any."""
    if capture is None:
        return None
    text = bytes(capture.stdout).decode("utf-8", errors="replace")
    candidates = [line for line in reversed(text.splitlines()) if line.strip()]
    candidates.append(text)
    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
        except (TypeError, ValueError):
            continue
        if _is_cursor_result(parsed):
            return parsed
    return None


def fold_native_result_usage(
    capture: NativeCapture | None,
    *,
    chats_dir: Path | None = None,
) -> str:
    """Fold one finished native's result; return the session's total."""
    payload = native_result_payload(capture)
    if payload is None:
        return ""
    from yoke_harness.cursor_usage_attestation import attest_cursor_usage

    usage = attest_cursor_usage(_with_served_model(payload, chats_dir=chats_dir))
    return usage_document(usage) if usage.measured() else ""


def fold_launch_native_result(
    launch_id: str,
    *,
    state_dir: Path | None = None,
    chats_dir: Path | None = None,
) -> str:
    """Fold the result of the native this launch started, by its capture."""
    from yoke_harness.session_relay_native_diagnostics import (
        NativeDiagnosticError,
        diagnostic_reference,
        native_diagnostic_path,
        read_native_capture,
    )

    try:
        capture = read_native_capture(
            native_diagnostic_path(
                diagnostic_reference(launch_id),
                state_dir=state_dir,
                create=False,
            )
        )
    except NativeDiagnosticError:
        return ""
    return fold_native_result_usage(capture, chats_dir=chats_dir)


def session_usage_document(session_id: str) -> str:
    """Return what this Cursor session's watermark has measured so far.

    Empty means nothing was measured for this session — either it is not a
    Cursor session at all, or no result has been folded for it yet. A
    watermark written for a different artifact is not read as this one, so
    another harness's totals can never answer here.
    """
    if not str(session_id or "").strip():
        return ""
    from yoke_harness.cursor_usage_attestation import attest_cursor_usage

    usage = attest_cursor_usage({"session_id": str(session_id).strip()})
    return usage_document(usage) if usage.measured() else ""


def _is_cursor_result(parsed: object) -> bool:
    if not isinstance(parsed, dict) or parsed.get("type") != RESULT_TYPE:
        return False
    usage = parsed.get("usage")
    return isinstance(usage, dict) and all(
        field in usage for field in RESULT_USAGE_FIELDS
    )


def _with_served_model(
    payload: Mapping[str, Any],
    *,
    chats_dir: Path | None,
) -> dict[str, Any]:
    """Name the model this conversation ran under, when the store states it."""
    reading = dict(payload)
    if any(str(reading.get(key) or "").strip() for key in ("model", "model_id")):
        return reading
    from yoke_harness.cursor_executed_model import executed_model_for_payload

    model = executed_model_for_payload(reading, chats_dir=chats_dir)
    if model:
        reading["model"] = model
    return reading


__all__ = [
    "RESULT_TYPE",
    "RESULT_USAGE_FIELDS",
    "fold_launch_native_result",
    "fold_native_result_usage",
    "native_result_payload",
    "session_usage_document",
]
