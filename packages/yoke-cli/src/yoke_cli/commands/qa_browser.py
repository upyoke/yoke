"""Tool-shaped ``yoke qa browser`` machine-substrate utilities.

Setup, status, and screenshot operate on this machine's Playwright daemon
under ``~/.yoke/browser-runtime/``. Materialized Browser check and Browser
inspection cases execute through ``yoke qa case run --requirement-id``;
this family deliberately has no parallel aggregate runner.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from yoke_cli.commands._helpers import parse_or_usage_error


QA_BROWSER_SCREENSHOT_USAGE = (
    "yoke qa browser screenshot <url> --output PATH "
    "[--viewport WxH] [--annotate]"
)

_QA_BROWSER_SCREENSHOT_HELP_DEEP = """\
Capture one screenshot of a URL with the machine-local browser daemon
(started on demand, bounded retries). This is diagnostic capture tooling;
it does not record a QA verdict or replace `yoke qa case run`.

Worked example:

  yoke qa browser screenshot "$_eph_url/dashboard" \\
      --output /tmp/yok-1234-dashboard.png

Stdout: the daemon's JSON snapshot response.
Exit codes: 0 captured; 1 capture failed; 2 prerequisite failure
(daemon could not start, bad usage).

Source-dev/admin module forms are intentionally not part of this product
surface; use the installed ``yoke qa browser screenshot`` command."""


def qa_browser_screenshot(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa browser screenshot",
        description=(
            f"{QA_BROWSER_SCREENSHOT_USAGE}\n\n"
            f"{_QA_BROWSER_SCREENSHOT_HELP_DEEP}"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("url", help="Absolute URL to capture.")
    parser.add_argument(
        "--output", required=True,
        help="Local file path the PNG is written to.",
    )
    parser.add_argument(
        "--viewport", default=None,
        help="Viewport WxH (e.g. 1280x720; default: daemon default).",
    )
    parser.add_argument(
        "--annotate", action="store_true",
        help="Annotate interactive elements in the capture.",
    )
    parsed = parse_or_usage_error(parser, args, QA_BROWSER_SCREENSHOT_USAGE)
    if parsed is None:
        return 2

    try:
        from yoke_harness import browser_client
        from yoke_harness.browser_qa_daemon import ensure_daemon_running
    except ImportError as exc:
        print(
            "yoke qa browser screenshot requires yoke-harness in the "
            f"product install: {exc}",
            file=sys.stderr,
        )
        return 2

    daemon_error = ensure_daemon_running()
    if daemon_error:
        print(
            f"yoke qa browser screenshot: browser daemon unavailable: "
            f"{daemon_error}",
            file=sys.stderr,
        )
        return 2

    try:
        result = browser_client.snapshot_screenshot(
            parsed.url,
            annotate=parsed.annotate,
            output_path=parsed.output,
            viewport=parsed.viewport,
        )
    except RuntimeError as exc:
        print(f"yoke qa browser screenshot: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0


# CLI token tuples -> adapter, merged into the launcher's tool-shaped
# table by yoke_cli.commands.tool_shaped.
QA_BROWSER_SUBCOMMANDS = {
    ("qa", "browser", "screenshot"): qa_browser_screenshot,
}

QA_BROWSER_USAGE = {
    "yoke qa browser screenshot": (
        "Capture one URL screenshot with the machine-local browser daemon "
        "for substrate diagnostics."
    ),
}


__all__ = [
    "QA_BROWSER_SCREENSHOT_USAGE",
    "QA_BROWSER_SUBCOMMANDS",
    "QA_BROWSER_USAGE",
    "qa_browser_screenshot",
]
