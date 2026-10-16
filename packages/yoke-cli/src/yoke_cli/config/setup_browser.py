"""Browser-step data shared by setup's terminal and agent surfaces."""

from __future__ import annotations

import json
import sys
import threading
from typing import Any, Callable, Mapping

from yoke_cli.config.hosted_machine_browser import BrowserOpenResult, open_url
from yoke_cli.config import github_response_safety
from yoke_contracts.designed_wait import announce_designed_wait, poll_every

OPENING_NOTICE = "Opening your browser…"


def open_after_notice(
    shell: Any, url: str, *, opener: Callable[[str], BrowserOpenResult] | None = None
) -> BrowserOpenResult:
    """A browser worker waits until the terminal has painted its notice.

    A shell without a terminal (agent mode) never opens a browser: the person
    opens the link the agent shows them.
    """
    if not getattr(shell, "opens_browser", True):
        return open_requested(url, None)
    painted = threading.Event()
    shell.call_from_thread(shell.call_after_refresh, painted.set)
    if not painted.wait(10):
        return BrowserOpenResult(
            False,
            reason="browser_notice_not_rendered: copy the link or restart setup before opening",
            attempted=False,
        )
    return (opener or open_url)(url)


def action(
    url: str, instructions: str, *, user_code: str | None = None
) -> dict[str, Any]:
    """Public instructions only; device codes and credentials never belong here."""
    return {"url": url, "user_code": user_code, "instructions": instructions}


def open_requested(
    url: str, browser_open: Callable[[str], Any] | None
) -> BrowserOpenResult:
    """Only an explicitly supplied terminal opener may launch a browser."""
    if browser_open is None:
        return BrowserOpenResult(False, reason="browser_not_requested", attempted=False)
    try:
        result = browser_open(url)
    except Exception as exc:
        return BrowserOpenResult(
            False,
            reason=f"browser_open_failed: {type(exc).__name__}: {exc}; copy the link and open it yourself",
        )
    if isinstance(result, BrowserOpenResult):
        return result
    return BrowserOpenResult(
        bool(result),
        method="requested-opener" if result else None,
        reason=None
        if result
        else "browser_open_returned_false: copy the link and open it yourself",
    )


def render_progress(event: Mapping[str, Any], *, json_mode: bool) -> None:
    """Flush human authorization data before polling; final stdout stays JSON."""
    request = event.get("browser_action")
    if event.get("phase") == "machine_authorization" and isinstance(request, Mapping):
        from yoke_cli.config.onboard_wizard_flow_machine_admission import approval_hint

        code = request.get("user_code")
        if code:
            event = {**event, "match_code": code, "approval_hint": approval_hint(code)}
    if json_mode:
        data = dict(event)
        if event.get("phase") in {"device_browser", "machine_authorization"}:
            data["wait"] = {
                "reason": "human_browser_approval",
                "max_seconds": event.get("expires_in"),
                "poll_interval_seconds": event.get("interval"),
                "silence_expected": True,
            }
        print(json.dumps(data, sort_keys=True), file=sys.stderr, flush=True)
        return
    if isinstance(request, Mapping):
        print(
            f"Open {github_response_safety.safe_error_text(request['url'])}",
            file=sys.stderr,
            flush=True,
        )
        if request.get("user_code"):
            label = "Match code" if event.get("match_code") else "One-time code"
            print(
                f"{label}: {github_response_safety.safe_error_text(request['user_code'])}",
                file=sys.stderr,
                flush=True,
            )
        print(
            github_response_safety.safe_error_text(request["instructions"]),
            file=sys.stderr,
            flush=True,
        )
        if event.get("approval_hint"):
            print(event["approval_hint"], file=sys.stderr, flush=True)
    elif event.get("phase") == "github_access_propagation_retry":
        print(
            f"GitHub is finishing authorization; retrying the access check in {event.get('retry_in_seconds'):g}s...",
            file=sys.stderr,
            flush=True,
        )
    if event.get("phase") == "device_browser":
        announce_designed_wait(
            "GitHub browser approval",
            max_wait_seconds=float(event.get("expires_in") or 0),
            cadence=poll_every(float(event.get("interval") or 5)),
        )


def open_in_wizard(
    shell: Any, url: str, *, step: str, on_success: Callable[[BrowserOpenResult], None]
) -> None:
    """Paint notice and copy keys before the browser worker starts."""
    from yoke_cli.config.onboard_wizard_state import CopyTarget

    def completed(browser: BrowserOpenResult) -> None:
        shell._setup_browser_result = browser
        on_success(browser)

    shell._run_checking(
        step=step,
        title=OPENING_NOTICE,
        message="Return here after finishing the browser step.",
        detail_lines=[url],
        copy_targets=(CopyTarget("the browser link", url, is_url=True),),
        work=lambda: open_after_notice(shell, url),
        on_success=completed,
        on_error=lambda exc: completed(
            BrowserOpenResult(
                False,
                reason=f"browser_open_failed: {exc}; copy the link and open it yourself",
            )
        ),
        group="onboard-browser-open",
    )


def status_line(shell: Any) -> str:
    browser = getattr(shell, "_setup_browser_result", None)
    if browser is None:
        return "Ctrl-Y copies the link; Ctrl-O opens it."
    if browser.opened:
        return "Browser opened; finish this step and return here."
    return f"browser_open_failed: {browser.reason}; Ctrl-Y copies the link so you can open it yourself."


__all__ = ["OPENING_NOTICE", "action", "open_requested", "render_progress"]
