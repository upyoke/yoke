"""Open and close the daemon page one run owns for its whole life.

A run that walks several steps addresses one page by id from its first step
to its last. That is what keeps the route and the viewport it establishes its
own: without an id the daemon hands out whichever page it is holding, so the
run after this one inherits where this one left off.

Parent-bound symbols resolve through ``yoke_core.domain.browser_client`` at
call time, so the patch seam described in that module's docstring reaches this
sibling too.
"""

from __future__ import annotations

from typing import Dict, Optional

from yoke_contracts.browser_daemon_api import (
    EXEC_PAGE_CLOSE_PATH,
    EXEC_PAGE_PATH,
)


def _bc():
    from yoke_core.domain import browser_client

    return browser_client


def open_owned_page(
    viewport: Dict[str, int],
    page_id: Optional[str] = None,
) -> str:
    """Open a page sized to *viewport* and return the id that addresses it.

    A run that lives once takes the generated id. A caller that spans separate
    processes names its page, and the same page answers for as long as it
    stays open — returned as it stands, because the size and route its owner
    established are the state it came back for.
    """
    body: Dict[str, object] = {"viewport": dict(viewport)}
    if page_id:
        body["pageId"] = str(page_id)
    response = _bc().daemon_request(EXEC_PAGE_PATH, body)
    opened = (response.get("data") or {}).get("pageId")
    if not opened:
        raise RuntimeError(
            "the browser daemon opened no page for this run "
            f"(response: {response}). Without one there is nothing to run "
            "steps against; check the daemon with "
            "`python3 -m yoke_core.domain.browser_client daemon health`."
        )
    return str(opened)


def close_owned_page(page_id: str) -> None:
    """Release the run's page. A page already gone is already released."""
    _bc().daemon_request(EXEC_PAGE_CLOSE_PATH, {"pageId": str(page_id)})


__all__ = ["close_owned_page", "open_owned_page"]
