"""Shared GitHub issue dedup helper.

Both ``backlog_github_sync`` and ``epic_task_sync_github`` need to dedup-search
GitHub issues by exact bracketed title prefix before creating a new issue.
GitHub's full-text title search is fuzzy on bracketed and numeric tokens, so a
token match is not a guarantee of an exact bracketed-prefix match — e.g.
searching ``[YOK-XXXX] in:title`` returns issues whose title merely contains
``1500`` as a substring (such as another ticket whose title contains
``1000-1500 lines``). This helper centralizes the REST call and exact-prefix
post-filter so the same protection runs at every dedup call site.

When in doubt, prefer creating a duplicate issue over reusing the wrong one.

Yoke does NOT use the ``gh`` CLI; the search dispatches through the typed
:func:`yoke_core.domain.github_rest.list_issues` surface (Search API).
"""

from __future__ import annotations

import sys
from typing import Optional, TextIO

from yoke_core.domain import github_rest


def search_existing_issue(
    title_prefix: str,
    *,
    project: str,
    stderr: Optional[TextIO] = None,
) -> Optional[tuple[str, str]]:
    """Search GitHub for an existing issue whose title begins with ``title_prefix``.

    Returns ``(issue_number, title)`` for the first candidate that passes the
    exact-prefix check, or ``None`` when:

    - The REST search fails.
    - No candidate's title starts with ``title_prefix``.
    """
    err: TextIO = stderr if stderr is not None else sys.stderr
    try:
        # GitHub's Search API requires `is:issue` (or `is:pull-request`);
        # without it the request returns HTTP 422 and the whole dedup pass
        # falls back to creating a duplicate.
        candidates = github_rest.list_issues(
            project=project,
            search=f"{title_prefix} in:title is:issue",
            limit=5,
        )
    except github_rest.RestTransportError as exc:
        print(
            f"Warning: GitHub dedup search failed for "
            f"{title_prefix!r}: {exc}. Skipping reuse to avoid misattribution.",
            file=err,
        )
        return None

    for entry in candidates:
        title = entry.title
        number = entry.number
        if title.startswith(title_prefix) and number:
            return (str(number), title)
    return None
