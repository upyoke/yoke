"""Tool-shaped ``yoke qa browser`` machine-substrate utilities.

Setup, status, screenshot, and one-step execution operate on this machine's
Playwright daemon under ``~/.yoke/browser-runtime/``. Materialized Browser
check and Browser inspection cases execute through
``yoke qa case run --requirement-id``; this family deliberately has no
parallel aggregate runner.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from yoke_cli.commands._helpers import parse_or_usage_error, usage_error
from yoke_cli.config.project_selection import required_project_context
from yoke_contracts.browser_step_schema import declared_schema_help
from yoke_contracts.project_defaults import MissingProjectError


QA_BROWSER_SCREENSHOT_USAGE = (
    "yoke qa browser screenshot <url> --output PATH "
    "[--viewport WxH] [--annotate] [--project P] [--identity NAME]"
)
QA_BROWSER_STEP_USAGE = (
    "yoke qa browser step --base-url URL --step-json JSON "
    "[--output-dir PATH] [--project P] [--identity NAME] [--page NAME]"
)

_PROJECT_FLAG_HELP = (
    "Project whose signed-in browser profile to use (default: "
    "$YOKE_PROJECT, then this checkout's project). With none, the "
    "command refuses and lists the projects you can use."
)
_IDENTITY_FLAG_HELP = (
    "Browser identity to use (default: `default`). Each identity has its "
    "own profile and browser process. An identity never signed in on this "
    "machine starts signed out; the log names the "
    "`yoke browser authorize --identity NAME` command that signs it in."
)

_QA_BROWSER_SCREENSHOT_HELP_DEEP = """\
Capture one screenshot of a URL with this machine's browser process,
which starts if it is not running. Use it to look at a page; it does not
record a QA verdict or replace `yoke qa case run`.

Worked example:

  yoke qa browser screenshot "$_eph_url/dashboard" \\
      --output /tmp/yok-1234-dashboard.png

Stdout: the browser's JSON response.
Exit codes: 0 captured; 1 capture failed; 2 could not start
(the browser did not start, or the command was used wrongly)."""


def qa_browser_screenshot(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa browser screenshot",
        usage=QA_BROWSER_SCREENSHOT_USAGE,
        description=_QA_BROWSER_SCREENSHOT_HELP_DEEP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("url", help="Absolute URL to capture.")
    parser.add_argument(
        "--output",
        required=True,
        metavar="PATH",
        help="Local file to write the PNG to.",
    )
    parser.add_argument(
        "--viewport",
        default=None,
        metavar="WxH",
        help="Window size, e.g. 1280x720 (default: the browser's default).",
    )
    parser.add_argument(
        "--annotate",
        action="store_true",
        help="Mark the elements you can interact with in the capture.",
    )
    parser.add_argument("--project", metavar="P", help=_PROJECT_FLAG_HELP)
    parser.add_argument("--identity", metavar="NAME", help=_IDENTITY_FLAG_HELP)
    parsed = parse_or_usage_error(parser, args, QA_BROWSER_SCREENSHOT_USAGE)
    if parsed is None:
        return 2

    try:
        from yoke_harness import browser_client
        from yoke_harness.browser_qa_daemon import ensure_daemon_running
        from yoke_harness.browser_daemon_profile import project_scope
    except ImportError as exc:
        print(
            "yoke qa browser screenshot requires yoke-harness in the "
            f"product install: {exc}",
            file=sys.stderr,
        )
        return 2

    try:
        parsed.project = required_project_context(parsed.project)
    except MissingProjectError as exc:
        return usage_error(str(exc))
    daemon_error = ensure_daemon_running(parsed.project, parsed.identity)
    if daemon_error:
        print(
            f"yoke qa browser screenshot: browser daemon unavailable: {daemon_error}",
            file=sys.stderr,
        )
        return 2

    with project_scope(parsed.project, parsed.identity):
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


def qa_browser_step(args: List[str]) -> int:
    """Execute one agent-selected step with the machine-local browser."""
    parser = argparse.ArgumentParser(
        prog="yoke qa browser step",
        usage=QA_BROWSER_STEP_USAGE,
        description=declared_schema_help(),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--base-url", required=True, metavar="URL", help="Base URL for the step."
    )
    parser.add_argument(
        "--step-json", required=True, metavar="JSON", help="One step as a JSON object."
    )
    parser.add_argument(
        "--output-dir", metavar="PATH", help="Folder for files the step writes."
    )
    parser.add_argument("--project", metavar="P", help=_PROJECT_FLAG_HELP)
    parser.add_argument("--identity", metavar="NAME", help=_IDENTITY_FLAG_HELP)
    parser.add_argument(
        "--page",
        metavar="NAME",
        help="Named page keeps its state between calls until the daemon stops "
        "(after 10 idle minutes); default: exploratory.",
    )
    parsed = parse_or_usage_error(parser, args, QA_BROWSER_STEP_USAGE)
    if parsed is None:
        return 2
    if parsed.page is not None and not parsed.page.strip():
        print(
            "yoke qa browser step: page_name_blank: pass --page NAME "
            "with a nonblank name, or omit --page for exploratory.",
            file=sys.stderr,
        )
        return 2
    try:
        step = json.loads(parsed.step_json)
    except json.JSONDecodeError as exc:
        print(f"yoke qa browser step: invalid step JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(step, dict):
        print("yoke qa browser step: step JSON must be an object", file=sys.stderr)
        return 2
    try:
        from yoke_harness import browser_client
        from yoke_harness.browser_qa_daemon import ensure_daemon_running
        from yoke_harness.browser_daemon_profile import project_scope
    except ImportError as exc:
        print(
            f"yoke qa browser step requires yoke-harness in the product install: {exc}",
            file=sys.stderr,
        )
        return 2
    try:
        parsed.project = required_project_context(parsed.project)
    except MissingProjectError as exc:
        return usage_error(str(exc))
    daemon_error = ensure_daemon_running(parsed.project, parsed.identity)
    if daemon_error:
        print(
            f"yoke qa browser step: browser daemon unavailable: {daemon_error}",
            file=sys.stderr,
        )
        return 2
    with project_scope(parsed.project, parsed.identity):
        try:
            page_id = browser_client.ensure_page(
                parsed.page or browser_client.EXPLORATORY_PAGE_ID
            )
            result = browser_client.execute_step(
                step,
                parsed.base_url,
                output_dir=parsed.output_dir,
                page_id=page_id,
            )
        except RuntimeError as exc:
            print(f"yoke qa browser step: {exc}", file=sys.stderr)
            return 1
    print(json.dumps(result))
    return 0


# CLI token tuples -> adapter, merged into the launcher's tool-shaped
# table by yoke_cli.commands.tool_shaped.
QA_BROWSER_SUBCOMMANDS = {
    ("qa", "browser", "screenshot"): qa_browser_screenshot,
    ("qa", "browser", "step"): qa_browser_step,
}

QA_BROWSER_USAGE = {
    "yoke qa browser screenshot": (
        "Take one screenshot of a web page with this machine's browser."
    ),
    "yoke qa browser step": ("Run one JSON browser step with this machine's browser."),
}


__all__ = [
    "QA_BROWSER_SCREENSHOT_USAGE",
    "QA_BROWSER_STEP_USAGE",
    "QA_BROWSER_SUBCOMMANDS",
    "QA_BROWSER_USAGE",
    "qa_browser_screenshot",
    "qa_browser_step",
]
