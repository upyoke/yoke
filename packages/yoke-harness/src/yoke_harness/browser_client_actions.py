"""Step execution and screenshot actions for the Browser QA daemon client."""

from __future__ import annotations

from typing import Any, Dict, Optional

from yoke_contracts.browser_daemon_api import EXEC_PAGE_PATH, EXEC_STEP_PATH
from yoke_contracts.browser_qa_contract import DEFAULT_BROWSER_VIEWPORT


#: The page an exploratory agent works on. That agent submits one step per
#: command, each in its own process, so its page is named rather than
#: generated: the same page answers every call for as long as the daemon
#: lives, which is what lets it open a menu in one command and act on it in
#: the next. An authored QA case takes a fresh page per run instead, so the
#: two never observe each other's screen.
EXPLORATORY_PAGE_ID = "exploratory"


def _client():
    # Preserve the parent module's daemon_request patch seam for callers and
    # tests while keeping action construction out of the lifecycle module.
    from yoke_harness import browser_client

    return browser_client


def ensure_page(
    page_id: str = EXPLORATORY_PAGE_ID,
    viewport: Optional[Dict[str, int]] = None,
) -> str:
    """Return *page_id*, opening it at *viewport* when it is not open yet.

    An open page comes back as it stands. Its size and its route are the state
    the caller came back for, so reuse never resizes it.
    """
    body = {
        "pageId": str(page_id),
        "viewport": dict(viewport or DEFAULT_BROWSER_VIEWPORT),
    }
    response = _client().daemon_request(EXEC_PAGE_PATH, body)
    opened = (response.get("data") or {}).get("pageId")
    if not opened:
        raise RuntimeError(
            f"the browser daemon opened no page for {page_id!r} "
            f"(response: {response}). Without one there is nothing to run "
            "steps against; check the daemon with `yoke qa browser status`."
        )
    return str(opened)


def execute_step(
    step_json: Dict[str, Any],
    base_url: str,
    output_dir: Optional[str] = None,
    *,
    page_id: str,
) -> Dict[str, Any]:
    """Execute one step on the page *page_id* addresses."""
    body: Dict[str, Any] = {
        "step": step_json,
        "baseUrl": base_url,
        "pageId": str(page_id),
    }
    if output_dir:
        body["outputDir"] = output_dir
    return _client().daemon_request(EXEC_STEP_PATH, body)


def parse_viewport(viewport: str) -> tuple[int, int]:
    parts = viewport.lower().split("x")
    if len(parts) != 2:
        raise ValueError(f"Invalid viewport format: {viewport!r} (expected WxH)")
    return int(parts[0]), int(parts[1])


def snapshot_screenshot(
    url: str,
    annotate: bool = False,
    output_path: Optional[str] = None,
    viewport: Optional[str] = None,
) -> Dict[str, Any]:
    body: Dict[str, Any] = {"url": url, "annotate": annotate}
    if output_path:
        body["outputPath"] = output_path
    if viewport:
        width, height = parse_viewport(viewport)
        body["viewport"] = {"width": width, "height": height}
    return _client().daemon_request("/api/snapshot/screenshot", body)


__all__ = [
    "EXPLORATORY_PAGE_ID",
    "ensure_page",
    "execute_step",
    "parse_viewport",
    "snapshot_screenshot",
]
