"""Build Yokepedia from the current Yoke source checkout, then open it.

The build is the registered teaching scanner that ``yoke dev run`` runs in
place, so it needs no harness session or work claim.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path
from typing import Sequence

from yoke_core.tools import source_dev_run, source_dev_scanner

BUILD_COMMAND = ("python3", "docs/teaching/tools/build.py")
PAGE = Path("docs/teaching/views/yokepedia.html")
USAGE = "yoke dev yokepedia [--no-open]"
DESCRIPTION = (
    "Build Yokepedia, the guide to what Yoke teaches, from the current "
    "directory's Yoke source checkout and open it in a browser. The page is "
    "one self-contained file that works from a file URL."
)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="yoke dev yokepedia", description=DESCRIPTION)
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Build the page and print its path without opening a browser.",
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root, error = source_dev_scanner.checkout_root()
    if root is None:
        print(f"error: {error}", file=sys.stderr)
        return 1
    code = source_dev_run.run(list(BUILD_COMMAND))
    if code:
        print(
            "error: yokepedia_build_failed: the page was not replaced; fix the "
            "problems above, then rerun `yoke dev yokepedia`",
            file=sys.stderr,
        )
        return code
    page = root / PAGE
    if args.no_open:
        print(page)
        return 0
    if _open(page):
        print(f"Opened Yokepedia: {page}")
    else:
        print(f"Could not open a browser. Open this file: {page}")
    return 0


def _open(page: Path) -> bool:
    try:
        return webbrowser.open(page.as_uri())
    except webbrowser.Error:
        return False


__all__ = ["BUILD_COMMAND", "DESCRIPTION", "PAGE", "USAGE", "main"]
