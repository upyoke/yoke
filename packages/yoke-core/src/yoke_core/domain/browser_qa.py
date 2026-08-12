"""Low-level Browser method-case runner substrate.

The user-facing entry is ``yoke qa case run --requirement-id R``. The shared
case runner calls :func:`execute_scenario` for exactly one materialized
Browser check or Browser inspection requirement. This module preserves the
daemon, step, and artifact primitives used by that path; it is not a second
CLI.

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

This file keeps the load-bearing ``import time`` (used by tests via
``mock.patch("...browser_qa.time.sleep")``) and re-exports of the low-level
helpers the case runner exercises.
"""

from __future__ import annotations

# ``time`` is intentionally imported here even though the parent module
# never calls it directly: tests use ``mock.patch("...browser_qa.time.sleep")``
# to suppress real sleeps in the daemon retry loop. Removing this import
# would silently no-op those patches and let tests sleep for real.
import time  # noqa: F401

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
    "_DAEMON_MAX_RETRIES",
    "_SCREENSHOT_ACTIONS",
    "_build_code_identity",
    "_build_run_payload",
    "_resolve_repo_root",
    "_validate_freshness_inputs",
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
