"""Tool-shaped ``yoke qa browser`` family — the browser-QA agent entries.

The browser-QA orchestrator (``run``) and the manual-fallback capture
(``screenshot``) execute on THIS machine (Playwright daemon under
``~/.yoke/browser-runtime/``, screenshots on local disk), so they are
client orchestrations like the git hook bodies. ``yoke-cli`` owns only
the flag adapter; the machine-local daemon/client runner lives in
``yoke-harness``. The orchestrator's DB legs ARE dispatcher function ids
(``qa.browser_context.get`` / ``qa.run.add`` / ``qa.run.complete`` /
``qa.artifact.add``), so the flow works from external projects over the
https relay without a Yoke source checkout or local Postgres.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from yoke_cli.commands._helpers import (
    client_project_context,
    ensure_handlers_loaded,
    parse_or_usage_error,
)
from yoke_cli.transport.dispatcher import build_actor, call_dispatcher

QA_BROWSER_RUN_USAGE = (
    "yoke qa browser run --item PREFIX-N [--project P] [--base-url URL] "
    "[--expected-branch BRANCH --expected-sha SHA]"
)

_QA_BROWSER_RUN_HELP_DEEP = """\
Run every unwaived browser_smoke / browser_diff qa_requirement on the item:
fetch the scenario context (qa.browser_context.get), validate deployment
freshness and base-url reachability, ensure the machine-local browser
daemon is running (materialized on first use), execute the scenario steps,
and record qa_runs + qa_artifacts through the dispatcher write ids.

Worked examples:

  yoke qa browser run --item EXT-1732 --base-url http://localhost:3000
  yoke qa browser run --item YOK-N --project yoke \\
      --expected-branch YOK-N --expected-sha abc123def456

Flag matrix:

  flag               required  default                       value shape
  --item             yes       —                             PREFIX-N or project-local number
  --project          no        checkout's mapped project     project slug or id
  --base-url         no        success_policy.base_url       http(s)://host[:port]
  --expected-branch  no        — (pair with --expected-sha)  branch name
  --expected-sha     no        — (pair with --expected-branch) full HEAD SHA

Recording the runs requires an active work-claim on the item
(claims.work.acquire); the context read does not.

Stdout: JSON summary {"verdict":"pass|fail","runs":[...]}.
Exit codes: 0 all scenarios pass; 1 at least one failed; 2 prerequisite
failure (no requirements, unreachable URL, daemon failure, SHA mismatch,
context fetch failure, incomplete freshness args)."""


def qa_browser_run(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke qa browser run",
        description=f"{QA_BROWSER_RUN_USAGE}\n\n{_QA_BROWSER_RUN_HELP_DEEP}",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--item", required=True,
        help="Target item (PREFIX-N or project-local number).",
    )
    parser.add_argument(
        "--base-url", dest="base_url", default="",
        help="Base URL for browser tests (default: success_policy.base_url).",
    )
    parser.add_argument(
        "--expected-branch", dest="expected_branch", default=None,
        help="Branch for deployment freshness (pair with --expected-sha).",
    )
    parser.add_argument(
        "--expected-sha", dest="expected_sha", default=None,
        help="HEAD SHA for deployment freshness (pair with --expected-branch).",
    )
    parsed = parse_or_usage_error(parser, args, QA_BROWSER_RUN_USAGE)
    if parsed is None:
        return 2

    project = client_project_context(parsed.project)
    if not project:
        print(
            "yoke qa browser run: no project context — pass --project, "
            "set $YOKE_PROJECT, or run from a registered checkout.",
        )
        return 2

    try:
        from yoke_harness import browser_qa
    except ImportError as exc:
        print(
            "yoke qa browser run requires yoke-harness in the product "
            f"install: {exc}",
            file=sys.stderr,
        )
        return 2

    ensure_handlers_loaded()
    actor = build_actor()
    result = browser_qa.execute_scenario(
        item_id=parsed.item,
        project=str(project),
        dispatcher=lambda function_id, target, payload: call_dispatcher(
            function_id=function_id,
            target=target,
            payload=payload,
            actor=actor,
        ),
        base_url=parsed.base_url,
        expected_branch=parsed.expected_branch,
        expected_sha=parsed.expected_sha,
    )
    print(result.to_json())
    return browser_qa.scenario_exit_code(result)


QA_BROWSER_SCREENSHOT_USAGE = (
    "yoke qa browser screenshot <url> --output PATH "
    "[--viewport WxH] [--annotate]"
)

_QA_BROWSER_SCREENSHOT_HELP_DEEP = """\
Capture one screenshot of a URL with the machine-local browser daemon
(started on demand, bounded retries). This is the manual-fallback capture
for the advance browser-QA gate when the orchestrator (`yoke qa browser
run`) fails to link artifacts: capture to a temp path, verify the file is
non-empty, then record the run/artifact through `yoke qa run add` +
`yoke qa artifact add`.

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
        from yoke_harness import browser_client, browser_qa
    except ImportError as exc:
        print(
            "yoke qa browser screenshot requires yoke-harness in the "
            f"product install: {exc}",
            file=sys.stderr,
        )
        return 2

    daemon_error = browser_qa.ensure_daemon_running()
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
    ("qa", "browser", "run"): qa_browser_run,
    ("qa", "browser", "screenshot"): qa_browser_screenshot,
}

QA_BROWSER_USAGE = {
    "yoke qa browser run": (
        "Run the item's browser QA scenarios on this machine; DB legs go "
        "through qa.* function ids (works over https from any project)."
    ),
    "yoke qa browser screenshot": (
        "Capture one URL screenshot with the machine-local browser daemon "
        "(the manual-fallback capture for the browser-QA gate)."
    ),
}


__all__ = [
    "QA_BROWSER_RUN_USAGE",
    "QA_BROWSER_SCREENSHOT_USAGE",
    "QA_BROWSER_SUBCOMMANDS",
    "QA_BROWSER_USAGE",
    "qa_browser_run",
    "qa_browser_screenshot",
]
