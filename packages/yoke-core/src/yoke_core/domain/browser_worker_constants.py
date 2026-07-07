"""Exit-code constants for ``yoke_core.domain.browser_worker``.

This tiny module sits at the bottom of the ``browser_worker*`` dependency
graph: it has no internal imports, so any sibling can import these
constants without risking a circular import. The parent module re-exports
them so callers can still import
``EXIT_OK`` and friends from ``yoke_core.domain.browser_worker``.
"""

from __future__ import annotations


EXIT_OK = 0
EXIT_FAIL = 1
EXIT_NOT_RUNNING = 2
EXIT_USAGE = 3
