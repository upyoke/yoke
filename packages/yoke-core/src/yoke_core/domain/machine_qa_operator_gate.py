"""Typed operator handoffs inside credential-local Machine QA execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import json
import time
from typing import Any
from urllib.parse import urlsplit

from yoke_core.domain.ssh_mac_terminal_capture import RunRemote
from yoke_core.domain.ssh_mac_terminal_recipe_support import (
    capture_recipe_transcript,
    send_recipe_keys,
)


_HEARTBEAT_SECONDS = 15.0
_DENIAL_MARKERS = (
    "authorization denied in the browser",
    "authorization expired",
    "hosted authorization expired",
    "this machine was denied in the browser",
)


@dataclass(frozen=True)
class OperatorGateResult:
    """Outcome of one typed operator handoff."""

    ok: bool
    transcript: str
    error_code: str | None = None


def _labeled_value(transcript: str, label: str) -> str | None:
    for line in transcript.splitlines():
        stripped = line.strip()
        if stripped.startswith(label):
            value = stripped.removeprefix(label).strip()
            if value:
                return value
    return None


def _approved_origin(url: str, allowed_base_urls: tuple[str, ...]) -> bool:
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.netloc:
        return False
    return any(
        (parsed.scheme, parsed.netloc)
        == (allowed.scheme, allowed.netloc)
        for allowed in (urlsplit(value) for value in allowed_base_urls)
    )


def _emit_browser_approval(
    transcript: str,
    *,
    allowed_base_urls: tuple[str, ...],
) -> bool:
    url = _labeled_value(transcript, "Open:")
    code = _labeled_value(transcript, "One-time code:")
    if (
        url is None
        or code is None
        or not _approved_origin(url, allowed_base_urls)
    ):
        return False
    print(
        json.dumps(
            {
                "event": "machine_qa.operator_gate",
                "kind": "machine_browser_approval",
                "url": url,
                "code": code,
            },
            sort_keys=True,
        ),
        flush=True,
    )
    return True


def run_machine_browser_approval(
    run: RunRemote,
    *,
    backend: str,
    session: str,
    action: Mapping[str, Any],
    progress_callback: Callable[[], None] | None,
    allowed_base_urls: tuple[str, ...],
) -> OperatorGateResult:
    """Emit the live approval coordinates, start polling, and retain authority."""
    transcript = capture_recipe_transcript(
        run,
        backend=backend,
        session=session,
    )
    if not _emit_browser_approval(
        transcript,
        allowed_base_urls=allowed_base_urls,
    ):
        return OperatorGateResult(
            False,
            transcript,
            "machine_browser_approval_context_missing",
        )
    if not send_recipe_keys(
        run,
        backend=backend,
        session=session,
        keys=action["keys"],
    ):
        return OperatorGateResult(
            False,
            transcript,
            "machine_browser_approval_input_failed",
        )
    timeout_seconds = float(action["gate_timeout_seconds"])
    completion_text = tuple(action["completion_text"])
    deadline = time.monotonic() + timeout_seconds
    next_heartbeat = 0.0
    while True:
        transcript = capture_recipe_transcript(
            run,
            backend=backend,
            session=session,
        )
        lowered = transcript.casefold()
        if all(marker in transcript for marker in completion_text):
            return OperatorGateResult(True, transcript)
        if any(marker in lowered for marker in _DENIAL_MARKERS):
            return OperatorGateResult(
                False,
                transcript,
                "machine_browser_approval_rejected",
            )
        now = time.monotonic()
        if now >= deadline:
            return OperatorGateResult(
                False,
                transcript,
                "machine_browser_approval_timed_out",
            )
        if progress_callback is not None and now >= next_heartbeat:
            try:
                progress_callback()
            except Exception:
                return OperatorGateResult(
                    False,
                    transcript,
                    "machine_browser_approval_heartbeat_failed",
                )
            next_heartbeat = now + _HEARTBEAT_SECONDS
        time.sleep(1.0)


__all__ = ["OperatorGateResult", "run_machine_browser_approval"]
