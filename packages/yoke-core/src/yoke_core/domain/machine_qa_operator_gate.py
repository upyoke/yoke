"""Typed operator handoffs inside credential-local Machine QA execution."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
import time
from typing import Any
from urllib.parse import urlsplit

from yoke_core.domain.ssh_mac_terminal_capture import RunRemote
from yoke_core.domain.ssh_mac_browser_approval import (
    BrowserApprovalResult,
    approve_machine_in_safari,
)
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
_APPROVAL_PATHS = frozenset({"/connect", "/machine"})


@dataclass(frozen=True)
class OperatorGateResult:
    """Outcome of one typed operator handoff."""

    ok: bool
    transcript: str
    error_code: str | None = None
    browser_evidence: dict[str, Any] | None = None
    browser_automation_error_code: str | None = None


def _labeled_value(transcript: str, label: str) -> str | None:
    for line in transcript.splitlines():
        stripped = line.strip().lstrip("-•*").lstrip()
        if stripped.startswith(label):
            value = stripped.removeprefix(label).strip()
            if value:
                return value
    return None


def _approved_origin(url: str, allowed_base_urls: tuple[str, ...]) -> bool:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.path not in _APPROVAL_PATHS
        or parsed.query
        or parsed.fragment
    ):
        return False
    return any(
        (parsed.scheme, parsed.netloc) == (allowed.scheme, allowed.netloc)
        for allowed in (urlsplit(value) for value in allowed_base_urls)
    )


def _current_gate_transcript(transcript: str, code: str) -> str:
    """Exclude retained output from machine approvals that preceded this code."""

    code_index = transcript.rfind(code)
    return transcript[code_index:] if code_index >= 0 else transcript


def _emit_browser_approval(url: str, code: str) -> None:
    print(
        json.dumps(
            {
                "approval_automation": "self_approving_visible_safari",
                "event": "machine_qa.operator_gate",
                "kind": "machine_browser_approval",
                "self_approving": True,
                "url": url,
                "code": code,
            },
            sort_keys=True,
        ),
        flush=True,
    )


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
    return run_machine_browser_approval_with_io(
        read_transcript=lambda: capture_recipe_transcript(
            run,
            backend=backend,
            session=session,
        ),
        send_keys=lambda keys: send_recipe_keys(
            run,
            backend=backend,
            session=session,
            keys=keys,
        ),
        action=action,
        progress_callback=progress_callback,
        allowed_base_urls=allowed_base_urls,
        approve_browser=lambda url, code: approve_machine_in_safari(
            run,
            verification_url=url,
            user_code=code,
        ),
    )


def run_machine_browser_approval_with_io(
    *,
    read_transcript: Callable[[], str],
    send_keys: Callable[[Sequence[str]], bool],
    action: Mapping[str, Any],
    progress_callback: Callable[[], None] | None,
    allowed_base_urls: tuple[str, ...],
    approve_browser: Callable[[str, str], BrowserApprovalResult],
) -> OperatorGateResult:
    """Run one browser handoff through an already-authorized terminal surface."""
    transcript = read_transcript()
    url = _labeled_value(transcript, "Open:")
    code = _labeled_value(transcript, "One-time code:")
    if url is None or code is None or not _approved_origin(url, allowed_base_urls):
        return OperatorGateResult(
            False,
            transcript,
            "machine_browser_approval_context_missing",
        )
    _emit_browser_approval(url, code)
    if not send_keys(action["keys"]):
        return OperatorGateResult(
            False,
            transcript,
            "machine_browser_approval_input_failed",
        )
    approval = approve_browser(url, code)
    browser_automation_error_code = (
        None
        if approval.ok
        else approval.error_code or "machine_browser_approval_failed"
    )
    timeout_seconds = float(action["gate_timeout_seconds"])
    completion_text = tuple(action["completion_text"])
    gate_code = _labeled_value(transcript, "One-time code:")
    assert gate_code is not None
    deadline = time.monotonic() + timeout_seconds
    next_heartbeat = 0.0
    while True:
        transcript = read_transcript()
        gate_transcript = _current_gate_transcript(transcript, gate_code)
        lowered = gate_transcript.casefold()
        if all(marker in gate_transcript for marker in completion_text):
            return OperatorGateResult(
                True,
                transcript,
                browser_evidence=approval.evidence,
                browser_automation_error_code=browser_automation_error_code,
            )
        if any(marker in lowered for marker in _DENIAL_MARKERS):
            return OperatorGateResult(
                False,
                transcript,
                "machine_browser_approval_rejected",
                approval.evidence,
                browser_automation_error_code,
            )
        now = time.monotonic()
        if now >= deadline:
            return OperatorGateResult(
                False,
                transcript,
                "machine_browser_approval_timed_out",
                approval.evidence,
                browser_automation_error_code,
            )
        if progress_callback is not None and now >= next_heartbeat:
            try:
                progress_callback()
            except Exception:
                return OperatorGateResult(
                    False,
                    transcript,
                    "machine_browser_approval_heartbeat_failed",
                    approval.evidence,
                    browser_automation_error_code,
                )
            next_heartbeat = now + _HEARTBEAT_SECONDS
        time.sleep(1.0)


__all__ = [
    "OperatorGateResult",
    "run_machine_browser_approval",
    "run_machine_browser_approval_with_io",
]
