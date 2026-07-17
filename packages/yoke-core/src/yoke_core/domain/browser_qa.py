"""Browser QA scenario orchestrator.

The ONE canonical entry point for browser QA scenario execution. Fetches the
item's browser requirements + freshness context through the function-call
dispatcher (``qa.browser_context.get``), validates reachability, ensures the
browser daemon is running, iterates over steps, and records runs/artifacts
through ``qa.run.add`` / ``qa.run.complete`` / ``qa.artifact.add`` — so the
flow works from a Yoke checkout AND from an external project over the
https relay. Browser execution stays client-local.

Implementation is split across sibling modules under
``runtime/api/domain/browser_qa_*.py``:

- ``browser_qa_results``  — ``RunResult``, ``ScenarioResult``, ``_log``.
- ``browser_qa_daemon``   — daemon-startup auto-recovery + diagnostics.
- ``browser_qa_freshness``— reachability + freshness validation + payload
                            builders.
- ``browser_qa_steps``    — per-step dispatch and qa_run/qa_artifact
                            recording delegates.
- ``browser_qa_requirement`` — per-``qa_requirement`` step-loop owner.
- ``browser_qa_scenario`` — top-level driver (``execute_scenario``) plus
                            the ``qa.browser_context.get`` fetch.

This file keeps the CLI (``main`` + ``argparse``), the load-bearing
``import time`` (used by tests via ``mock.patch("...browser_qa.time.sleep")``),
and re-exports of every public + private name the test surface references.

Agent shape (works from any project checkout)::

    yoke qa browser run --item YOK-N --project P [--base-url URL] \\
        [--expected-branch BRANCH --expected-sha SHA]

Checkout-dev module form (same flags, ``--item-id N``)::

    python3 -m yoke_core.domain.browser_qa --item-id N --project P ...

Exit codes:
    0 = all scenarios pass
    1 = at least one scenario failed
    2 = prerequisite failure (unreachable URL, no requirements, daemon failure,
        incomplete freshness args, SHA mismatch, missing env record,
        missing deployed_sha, context fetch failure)

Stdout: JSON summary ``{"verdict":"pass|fail","runs":[...]}``
Stderr: progress/diagnostic messages
"""

from __future__ import annotations

import argparse
import sys
# ``time`` is intentionally imported here even though the parent module
# never calls it directly: tests use ``mock.patch("...browser_qa.time.sleep")``
# to suppress real sleeps in the daemon retry loop. Removing this import
# would silently no-op those patches and let tests sleep for real.
import time  # noqa: F401
from typing import List, Optional

# Re-exports from sibling modules. Keep these as plain imports so tests can
# patch attributes on this module via ``mock.patch.object(browser_qa, ...)``
# and any sibling helper that resolves them via this module observes the
# patch at call time.
from yoke_core.domain.browser_qa_results import (
    RunResult,
    ScenarioResult,
    _log,
)
from yoke_core.domain.browser_qa_daemon import (
    _DAEMON_MAX_RETRIES,
    _collect_daemon_diagnostics,
    _emit_daemon_startup_failed_event,
    _ensure_daemon_running,
)
from yoke_core.domain.browser_qa_freshness import (
    _build_code_identity,
    _build_run_payload,
    _resolve_repo_root,
    _validate_deployed_sha,
    _validate_freshness_inputs,
    _validate_reachability,
)
from yoke_core.domain.browser_qa_steps import (
    _SCREENSHOT_ACTIONS,
    _complete_run,
    _durable_artifact_handle,
    _execute_step,
    _is_screenshot_step,
    _presign_artifact,
    _record_artifact,
    _record_run,
    _upload_artifact,
)
from yoke_core.domain.browser_qa_scenario import (
    _fetch_browser_context,
    execute_scenario,
)


__all__ = [
    "RunResult",
    "ScenarioResult",
    "execute_scenario",
    "main",
    "scenario_exit_code",
    "_log",
    "_fetch_browser_context",
    "_validate_deployed_sha",
    "_validate_reachability",
    "_ensure_daemon_running",
    "_emit_daemon_startup_failed_event",
    "_record_run",
    "_complete_run",
    "_record_artifact",
    "_presign_artifact",
    "_upload_artifact",
    "_durable_artifact_handle",
    "_execute_step",
    "_is_screenshot_step",
    "_collect_daemon_diagnostics",
]


def scenario_exit_code(result: ScenarioResult) -> int:
    """Map a ScenarioResult to the orchestrator exit-code contract.

    Shared by the module CLI (``main``) and the launcher adapter
    (``yoke qa browser run``) so the two entries cannot drift.
    """
    if result.verdict == "error" or result.note in (
        "no_browser_requirements",
        "unreachable",
        "daemon_failure",
        "no_base_url",
        "vacuous_pass_prevented",
        "sha_mismatch",
        "context_unavailable",
    ):
        return 2
    if result.verdict == "fail":
        return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Browser QA scenario orchestrator")
    parser.add_argument("--item-id", type=int, required=True, help="Item ID")
    parser.add_argument("--project", required=True, help="Project ID")
    parser.add_argument("--base-url", default="", help="Base URL for browser tests")
    parser.add_argument(
        "--expected-branch",
        default=None,
        help="Expected branch name for SHA freshness validation (pair with --expected-sha)",
    )
    parser.add_argument(
        "--expected-sha",
        default=None,
        help="Expected HEAD SHA for freshness validation against deployed_sha (pair with --expected-branch)",
    )

    args = parser.parse_args(argv)

    result = execute_scenario(
        item_id=args.item_id,
        project=args.project,
        base_url=args.base_url,
        expected_branch=args.expected_branch,
        expected_sha=args.expected_sha,
    )

    print(result.to_json())
    return scenario_exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
