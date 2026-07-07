"""render_project — canonical CLI entrypoint for project template rendering.

Thin delegator onto :mod:`yoke_core.domain.project_renderer`, kept under
``runtime/api/tools/`` alongside other operator tools.

Usage::

    python3 -m yoke_core.tools.render_project <project> [--write] [--only ...]

Example::

    python3 -m yoke_core.tools.render_project buzz --write --only ops

Exit codes: 0 success, 1 render error, 2 argparse usage error.
"""

from __future__ import annotations

import sys
from typing import List, Optional

from yoke_core.domain import project_renderer


def main(argv: Optional[List[str]] = None) -> None:
    """Delegate straight to the domain CLI."""
    project_renderer.main(argv)


if __name__ == "__main__":
    main(sys.argv[1:])
