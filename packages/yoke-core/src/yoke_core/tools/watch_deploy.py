"""Run a deployment pipeline under the shared raw+progress watcher.

A hosted deploy is the longest command an operator runs — the release
bridge alone polls a GitHub Actions workflow for ten to twenty minutes —
and it was the last long command with no wrapper, so every invocation
hand-authored a capture-and-grep pair whose paired Monitor had no exit
sentinel and kept running after the deploy finished.

The wrapper drives the same module the ``yoke deployment-runs execute``
adapter drives and repeats its self-deploy authority check before starting
the watcher.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence

from yoke_cli.commands.adapters.deployment_execution_authority import (
    execution_connection_error,
)
from yoke_contracts.deployment_itemless_teaching import (
    FINALIZATION_PENDING_PREFIX,
    ITEMLESS_RELEASE_RECIPE,
    WATCH_DEPLOY_DESCRIPTION,
)
from yoke_core.domain.deploy_pipeline_pinned_source import (
    DRIVER_SOURCE_DRIFT_PREFIX,
    DeployPinnedSourceError,
)
from yoke_core.domain.deployment_run_driver_attachment import (
    PHASE_EXECUTING,
    PHASE_FREEZING_SOURCE,
)
from yoke_core.tools import _watch_runner, watch_preflight
from yoke_core.tools._watch_terminal_outcome import (
    OUTCOME_ONLY_WATCH_KINDS,
    PYTHON_EXCEPTION_PATTERN,
    emit_terminal_failure,
    is_python_exception_line,
)
from yoke_core.tools._watch_throttle import Classification, LineClass
from yoke_core.tools.deploy_pipeline_pinned_driver import (
    child_environment,
    frozen_driver_notice,
    pinned_driver_cwd,
)

WRAPPER_MODULE = "yoke_core.tools.watch_deploy"
KIND = "deploy"
# argparse prog for a direct module invocation; the CLI adapter passes
# the ``yoke watch deploy`` form so help reads back the command as typed.
DEFAULT_PROG = "watch_deploy"

# The engine ``yoke deployment-runs execute`` runs. Kept identical to that
# adapter's target so the wrapper cannot drift into driving something else.
ENGINE_MODULE = "yoke_core.domain.deploy_pipeline"

DEPLOY_URGENT_PREFIXES: tuple[str, ...] = (
    "Error:",
    "ERROR:",
    "Step runner diagnostic:",
    "fatal:",
    DRIVER_SOURCE_DRIFT_PREFIX,
)
# Terminal outcomes: the run's verdict, and what a reader must act on.
DEPLOY_SUMMARY_PREFIXES: tuple[str, ...] = (
    "Pipeline complete",
    FINALIZATION_PENDING_PREFIX,
)
DEPLOY_SUMMARY_RE = re.compile(r"has no member items")
# Routine motion remains classified for capture and diagnostics, but the
# outcome-only runner does not forward it to the user-facing stream.
DEPLOY_PROGRESS_PREFIXES: tuple[str, ...] = (
    "--- Stage:",
    "Deployment authority:",
    "Self-deploy driver frozen at",
)
# Indented by the pipeline, so these match anywhere on the line rather
# than at its start.
DEPLOY_PROGRESS_RE = re.compile(r"(Workflow run ID:|completed successfully)")
# The pipeline retries a temporary relay outage; keep it in raw diagnostics
# without waking the user before the run reaches an outcome.
DEPLOY_RELAY_UNAVAILABLE_RE = re.compile(r"status relay is temporarily unavailable")
FLEET_SCHEMA_REHEARSAL_START_RE = re.compile(r"^\s*Fleet schema rehearsal: uncovered\b")
FLEET_SCHEMA_REHEARSAL_COVERED_RE = re.compile(
    r"^\s*Fleet schema rehearsal: (?:covered\b|receipt covers\b)"
)


def classify_deploy_line(line: str) -> Classification:
    """Classify a single output line from the deployment pipeline.

    The user-facing stream is outcome-only. Workflow polls, progress and
    retryable relay warnings remain in the raw capture; terminal errors and
    summary lines are returned to the shared runner for immediate or final
    delivery. Liveness and deadlock checks still run without heartbeats.
    """
    if is_python_exception_line(line):
        return Classification(LineClass.URGENT)
    for prefix in DEPLOY_URGENT_PREFIXES:
        if line.startswith(prefix):
            return Classification(LineClass.URGENT)
    if DEPLOY_RELAY_UNAVAILABLE_RE.search(line):
        return Classification(LineClass.NOISE)
    for prefix in DEPLOY_SUMMARY_PREFIXES:
        if line.startswith(prefix):
            return Classification(LineClass.SUMMARY)
    if DEPLOY_SUMMARY_RE.search(line):
        return Classification(LineClass.SUMMARY)
    if FLEET_SCHEMA_REHEARSAL_START_RE.search(line):
        return Classification(LineClass.PROGRESS)
    if FLEET_SCHEMA_REHEARSAL_COVERED_RE.search(line):
        return Classification(LineClass.PROGRESS)
    for prefix in DEPLOY_PROGRESS_PREFIXES:
        if line.startswith(prefix):
            return Classification(LineClass.PROGRESS)
    if DEPLOY_PROGRESS_RE.search(line):
        return Classification(LineClass.PROGRESS)
    preflight_classification = watch_preflight.classify_preflight_line(line)
    if preflight_classification.cls != LineClass.NOISE:
        return preflight_classification
    return Classification(LineClass.NOISE)


def _build_deploy_progress_pattern() -> re.Pattern[str]:
    """Compose the public union regex from the class-specific regexes.

    Prefix alternatives are anchored to line start so a quoted ``Error:``
    inside a run summary does not read as a banner.
    """
    parts: list[str] = []
    parts.extend("^" + re.escape(p) for p in DEPLOY_URGENT_PREFIXES)
    parts.append(PYTHON_EXCEPTION_PATTERN.pattern)
    parts.extend("^" + re.escape(p) for p in DEPLOY_SUMMARY_PREFIXES)
    parts.extend("^" + re.escape(p) for p in DEPLOY_PROGRESS_PREFIXES)
    parts.append(DEPLOY_SUMMARY_RE.pattern)
    parts.append(DEPLOY_PROGRESS_RE.pattern)
    parts.append(FLEET_SCHEMA_REHEARSAL_START_RE.pattern)
    parts.append(FLEET_SCHEMA_REHEARSAL_COVERED_RE.pattern)
    parts.append(f"(?i:{watch_preflight.PREFLIGHT_PROGRESS_PATTERN.pattern})")
    return re.compile("|".join(parts))


DEPLOY_PROGRESS_PATTERN = _build_deploy_progress_pattern()


def deployment_connection_error(run_id: str) -> str | None:
    """Mirror the execute adapter's ordinary/self-deploy distinction."""
    refusal = execution_connection_error(run_id)
    return f"watch_deploy: {refusal}" if refusal else None


def _engine_argv(args: Sequence[str]) -> list[str]:
    """Build the underlying pipeline invocation argv."""
    return [sys.executable, "-m", ENGINE_MODULE, *list(args)]


def _parse_args(
    argv: Sequence[str],
    prog: str = DEFAULT_PROG,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=prog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=WATCH_DEPLOY_DESCRIPTION,
        epilog=(
            f"{ITEMLESS_RELEASE_RECIPE}\n\n"
            "Routine progress and watcher metadata are suppressed. "
            "Terminal errors and the final result are delivered immediately; "
            "the raw capture retains full output."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        _watch_runner.PRINT_STREAMING_PAIR_FLAG,
        dest="print_streaming_pair",
        action="store_true",
        help=_watch_runner.STREAMING_WAIT_HELP,
    )
    parser.add_argument(
        "--raw-capture",
        type=Path,
        default=None,
        help="Explicit raw capture file path. Defaults to a helper-resolved "
        "path under the project scratch root.",
    )
    parser.add_argument(
        "--progress-capture",
        type=Path,
        default=None,
        help="Explicit progress capture file path. Defaults to a helper-"
        "resolved path under the project scratch root.",
    )
    parser.add_argument(
        "passthrough",
        nargs=argparse.REMAINDER,
        help="Run id followed by any `deployment-runs execute` flags. Use "
        "``--`` to separate wrapper flags from them.",
    )
    return parser.parse_args(list(argv))


def _strip_separator(passthrough: list[str]) -> list[str]:
    """Strip a leading ``--`` argparse left in REMAINDER."""
    args = list(passthrough)
    if args and args[0] == "--":
        args = args[1:]
    return args


def _extract_print_streaming_pair(argv: list[str]) -> tuple[list[str], bool]:
    """Pull ``--print-streaming-pair`` out of any position in ``argv``.

    ``passthrough`` uses ``nargs=argparse.REMAINDER``, so the flag would
    otherwise be forwarded to the pipeline once it appears after the run
    id. Pre-extracting makes every position equivalent.
    """
    filtered: list[str] = []
    found = False
    for arg in argv:
        if arg == _watch_runner.PRINT_STREAMING_PAIR_FLAG:
            found = True
            continue
        filtered.append(arg)
    return filtered, found


def _hold_driver(run_id: str, *, phase: str, progress_capture: str = "") -> None:
    from yoke_core.domain.deploy_pipeline_control_plane import attach_driver

    attach_driver(run_id, phase=phase, progress_capture=progress_capture)


def _drop_driver(run_id: str) -> None:
    from yoke_core.domain.deploy_pipeline_control_plane import release_driver

    release_driver(run_id)


def _report_preflight_failure(
    message: str,
    raw_capture: Path,
    progress_capture: Path,
) -> int:
    """Write a preflight failure into the bound raw and progress captures."""
    return emit_terminal_failure(
        kind=KIND,
        message=message,
        exit_code=2,
        raw_capture=raw_capture,
        progress_capture=progress_capture,
    )


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    raw, print_streaming_pair_flag = _extract_print_streaming_pair(raw)
    ns = _parse_args(raw, prog)
    if print_streaming_pair_flag:
        ns.print_streaming_pair = True
    passthrough = _strip_separator(list(ns.passthrough))

    if ns.print_streaming_pair:
        raw_path, progress_path = _watch_runner.mint_capture_paths(KIND)
        return _watch_runner.print_wait_mode_invocation(
            kind=KIND,
            wrapper_module=WRAPPER_MODULE,
            wrapper_args=passthrough,
            raw_capture=raw_path,
            progress_capture=progress_path,
            outcome_only=KIND in OUTCOME_ONLY_WATCH_KINDS,
        )

    raw_path, progress_path = _watch_runner.bind_capture_paths(ns, KIND)
    if not passthrough:
        return _report_preflight_failure(
            "watch_deploy: missing run id", raw_path, progress_path
        )
    refusal = deployment_connection_error(passthrough[0])
    if refusal is not None:
        return _report_preflight_failure(refusal, raw_path, progress_path)

    from yoke_core.domain.deploy_pipeline_control_plane import (
        DeploymentControlPlaneError,
        DriverLivenessPump,
    )

    capture = str(progress_path)
    run_id = passthrough[0]
    held = False
    try:
        try:
            _hold_driver(run_id, phase=PHASE_FREEZING_SOURCE, progress_capture=capture)
            held = True
        except DeploymentControlPlaneError as exc:
            return _report_preflight_failure(
                f"watch_deploy: {exc}", raw_path, progress_path
            )
        try:
            with DriverLivenessPump(
                run_id, phase=PHASE_FREEZING_SOURCE, progress_capture=capture
            ).running():
                pinned_env = child_environment(run_id)
        except DeployPinnedSourceError as exc:
            return _report_preflight_failure(
                f"watch_deploy: {exc}", raw_path, progress_path
            )
        try:
            _hold_driver(run_id, phase=PHASE_EXECUTING, progress_capture=capture)
            held = True
        except DeploymentControlPlaneError as exc:
            return _report_preflight_failure(
                f"watch_deploy: {exc}", raw_path, progress_path
            )
        header = frozen_driver_notice(pinned_env) if pinned_env else None
        return _watch_runner.run_watcher(
            argv=_engine_argv(passthrough),
            classifier=classify_deploy_line,
            raw_capture=raw_path,
            progress_capture=progress_path,
            kind=KIND,
            cwd=pinned_driver_cwd(pinned_env),
            env=pinned_env,
            header_metadata=header,
            outcome_only=KIND in OUTCOME_ONLY_WATCH_KINDS,
            liveness=DriverLivenessPump(
                run_id, phase=PHASE_EXECUTING, progress_capture=capture
            ),
        )
    finally:
        if held:
            _drop_driver(run_id)


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
