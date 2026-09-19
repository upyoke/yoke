"""The browser daemon's HTTP surface, named once for every client of it.

Two Python clients talk to the same daemon — ``yoke_core.domain``'s, which
runs authored QA cases, and ``yoke_harness``'s, which an exploratory agent
drives one step per command. Neither can import the other, so the paths they
share are stated here rather than spelled twice.
"""

from __future__ import annotations

#: Run one step against a page the caller names.
EXEC_STEP_PATH = "/api/exec/step"

#: Open the page a run owns, or return a named page that is still open.
EXEC_PAGE_PATH = "/api/exec/page"

#: Release a page. A page already gone is already released.
EXEC_PAGE_CLOSE_PATH = "/api/exec/page/close"


__all__ = [
    "EXEC_PAGE_CLOSE_PATH",
    "EXEC_PAGE_PATH",
    "EXEC_STEP_PATH",
]
