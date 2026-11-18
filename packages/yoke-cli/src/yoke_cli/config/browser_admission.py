"""Hand private admission URLs to human browsers without echoing credentials."""

from __future__ import annotations

import re
import sys
import threading
from typing import Callable

from yoke_cli.config.hosted_machine_browser import BrowserOpenResult, open_url
from yoke_cli.transport.dispatcher import _resolve_session_id
from yoke_contracts.harness_family_identity import nearest_harness_family

_BROWSER_OPEN_DELAY_SECONDS = 0.5
_REASON_CODE = re.compile(r"[a-z][a-z0-9_]*")
BROWSER_NOT_ATTEMPTED = frozenset({"browser_open_disabled", "browser_agent_mode"})


def browser_recovery(command: str | None = None) -> str:
    action = f"`{command}`" if command else "this command"
    return (
        f"Run {action} from your own terminal on a machine with a display "
        "to open the browser and sign in."
    )


def open_private_url(
    url: str,
    *,
    disabled: bool = False,
    opener: Callable[[str], BrowserOpenResult] = open_url,
) -> BrowserOpenResult:
    if disabled:
        return BrowserOpenResult(opened=False, reason="browser_open_disabled")
    if _resolve_session_id() or nearest_harness_family():
        return BrowserOpenResult(opened=False, reason="browser_agent_mode")
    try:
        result = opener(url) if url else None
    except Exception:  # Opener failures can contain the complete private URL.
        result = None
    if result and result.opened:
        return BrowserOpenResult(opened=True, method=result.method)
    return BrowserOpenResult(opened=False, reason=_reason_code(result))


def _reason_code(result: BrowserOpenResult | None) -> str:
    """Keep only the opener's leading reason code; its detail can hold the URL."""
    reason = (result.reason if result else None) or ""
    code = re.split(r"[:;]", reason, maxsplit=1)[0].strip()
    return code if _REASON_CODE.fullmatch(code) else "browser_open_failed"


def schedule_browser_admission(url: str) -> None:
    """Open after server startup, reporting only a safe reason and recovery."""

    def open_and_report() -> None:
        result = open_private_url(url)
        if not result.opened:
            print(f"{result.reason}: {browser_recovery()}", file=sys.stderr, flush=True)

    opener = threading.Timer(_BROWSER_OPEN_DELAY_SECONDS, open_and_report)
    opener.daemon = True
    opener.start()
