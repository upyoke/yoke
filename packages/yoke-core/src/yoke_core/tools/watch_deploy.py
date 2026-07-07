"""Command-shaped watcher for ``yoke_core.domain.deploy_pipeline`` runs.

Owns the deploy line classifier so callers do not author a Monitor
filter per invocation. The deploy phase emits stage banners, executor
output (CI workflow polling, ephemeral verification, scripted
deploys), and approval halts; the wrapper keeps that filtering in one
reusable command-shaped surface.

The classifier maps:

- ``Error:`` / ``Warning:`` / ``fatal:`` headers and stage-failure
  banners (``Stage '<name>' failed``) → ``URGENT`` (immediate emit).
- ``--- Stage: <name> ... ---`` banners, ``Awaiting human approval``
  halts, ``Stage '<name>' completed successfully`` transitions,
      ``Pipeline complete`` / ``Pipeline already complete`` /
      ``Auto-created run`` terminal and startup lines, deployment
      authority summaries, and the same ``RESULT_FILE=`` /
      ``YOKE_REPO_ROOT=`` result emissions the merge wrapper recognizes
      → ``SUMMARY``.
- CI-gate poll output (``CI gate: checking``, ``Workflow status:``,
  ``Workflow run ID:``, ``Found existing run``, ``Existing run status:``,
  ``Waiting for workflow run``), trigger lifecycle output
  (``No existing run found``, ``Trigger failed, retrying``,
  ``--fresh:``), seed-flow convergence, and core-container build/push output
  (``[core-deploy] …`` from the in-process ``core-container-deploy``
  executor) → ``PROGRESS`` (time-window throttled).

Every other line is ``NOISE`` (raw capture only).

Usage::

    # Direct execution (Codex / shell): streams filtered progress to
    # stdout while preserving full output in the raw capture. Pass any
    # deploy_pipeline args after ``--``; the wrapper supplies the
    # ``python3 -m yoke_core.domain.deploy_pipeline`` prefix itself.
    python3 -m yoke_core.tools.watch_deploy -- <run-id-or-item-id>

    # Print the ready-to-paste streaming pair for Claude Code:
    python3 -m yoke_core.tools.watch_deploy --print-streaming-pair -- \\
        <run-id-or-item-id>

The wrapper preserves deploy_pipeline's exit code so callers can still
branch on success (0), stage failure (1), awaiting approval (2), and
usage/setup error (3).
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.tools import _watch_runner
from yoke_core.tools._watch_throttle import Classification, LineClass

WRAPPER_MODULE = "yoke_core.tools.watch_deploy"
KIND = "deploy"

# Per-class regexes. Each is line-oriented; callers feed one line at a
# time. Keeping them as separate constants lets tests exercise each
# class independently without re-parsing the union pattern.
DEPLOY_URGENT_PREFIXES: tuple[str, ...] = (
    "Error:",
    "ERROR:",
    "FAILED",
    "BLOCKED:",
    "Warning:",
    "fatal:",
)
# Stage-failure banner: ``Stage '<name>' failed (exit code: <rc>)``.
# Matches both the stderr ``Error: stage '<name>' failed`` and the
# preceding stdout summary so either path immediately classifies as
# URGENT.
DEPLOY_STAGE_FAILED_RE = re.compile(
    r"[Ss]tage\s+'[^']+'\s+failed\b",
)
DEPLOY_SUMMARY_PREFIXES: tuple[str, ...] = (
    "--- Stage:",
    "Awaiting human approval",
    # Terminal success line (``Pipeline complete for run <id>``) and the
    # already-done startup line are distinct prefixes — neither is a
    # prefix of the other.
    "Pipeline complete",
    "Pipeline already complete",
    "Auto-created run",
    "Deployment authority:",
    "RESULT_FILE=",
    "YOKE_REPO_ROOT=",
)
# Stage-success transition: ``  Stage '<name>' completed successfully``
# (leading whitespace because deploy_pipeline indents stage results).
DEPLOY_STAGE_OK_RE = re.compile(
    r"^\s*[Ss]tage\s+'[^']+'\s+completed\s+successfully\b",
)
# CI-gate polling and trigger lifecycle lines emitted from
# ``deploy_pipeline_executors`` and ``deploy_pipeline_reporting``, plus
# the ``[core-deploy]`` build/push milestones the in-process
# ``core-container-deploy`` executor emits (``deploy_core_container*``)
# — the longest-running stage work; without them the watcher is silent
# for the whole docker build/push. Its failure strings are raised and
# re-printed as ``ERROR: …``, which the URGENT prefixes catch first.
DEPLOY_PROGRESS_RE = re.compile(
    r"^\s*("
    r"CI gate:\s*checking"
    r"|Workflow status:"
    r"|Workflow run ID:"
    r"|Found existing run"
    r"|Existing run status:"
    r"|Waiting for workflow run"
    r"|No existing run found"
    r"|Trigger failed, retrying"
    r"|--fresh:"
    r"|Stage inputs present:"
    r"|Reconciled stage"
    r"|Seeded deployment flow config converged:"
    r"|Skipping ephemeral-verify"
    r"|Run already completed successfully"
    r"|Existing run \S+ has zero jobs"
    r"|Existing run \S+ failed"
    r"|\[core-deploy\]"
    r")",
)


def classify_deploy_line(line: str) -> Classification:
    """Classify a single deploy_pipeline output line.

    Order matters: failure lines that *also* contain other tokens must
    still classify as ``URGENT`` so they emit immediately. We check
    URGENT (prefix + stage-failed banner) before SUMMARY and PROGRESS.
    """
    for prefix in DEPLOY_URGENT_PREFIXES:
        if line.startswith(prefix):
            return Classification(LineClass.URGENT)
    if DEPLOY_STAGE_FAILED_RE.search(line):
        return Classification(LineClass.URGENT)
    for prefix in DEPLOY_SUMMARY_PREFIXES:
        if line.startswith(prefix):
            return Classification(LineClass.SUMMARY)
    if DEPLOY_STAGE_OK_RE.search(line):
        return Classification(LineClass.SUMMARY)
    if DEPLOY_PROGRESS_RE.search(line):
        return Classification(LineClass.PROGRESS)
    return Classification(LineClass.NOISE)


def _build_deploy_progress_pattern() -> re.Pattern[str]:
    """Compose the public union regex from the class-specific regexes.

    Mirrors the merge wrapper's approach: prefix alternatives are
    anchored to line start so a stray ``Error:`` mid-line does not
    count as a banner.
    """
    parts: list[str] = []
    parts.extend("^" + re.escape(p) for p in DEPLOY_URGENT_PREFIXES)
    parts.append(DEPLOY_STAGE_FAILED_RE.pattern)
    parts.extend("^" + re.escape(p) for p in DEPLOY_SUMMARY_PREFIXES)
    parts.append(DEPLOY_STAGE_OK_RE.pattern)
    parts.append(DEPLOY_PROGRESS_RE.pattern)
    return re.compile("|".join(parts))


# Public union pattern: kept for callers/tests that want a single
# "is this a signal line?" check.
DEPLOY_PROGRESS_PATTERN = _build_deploy_progress_pattern()


NESTED_DEPLOY_REJECTION_MESSAGE = (
    "watch_deploy expects bare deploy_pipeline args after --; "
    "do not include python3 -m yoke_core.domain.deploy_pipeline.\n"
    "Example: python3 -m yoke_core.tools.watch_deploy -- <run-id>"
)

# Match the bare interpreter names operators most commonly retype, plus
# the literal ``sys.executable`` token. Path forms reuse this against
# the basename so we accept them without separately enumerating prefixes.
_PYTHON_BASENAME_RE = re.compile(r"^python(\d+(\.\d+)?)?$")


def _looks_like_python_executable(token: str) -> bool:
    """Return True when ``token`` names a Python interpreter."""
    if token == "sys.executable":
        return True
    base = token.rsplit("/", 1)[-1]
    return bool(_PYTHON_BASENAME_RE.match(base))


def _is_nested_deploy_invocation(args: Sequence[str]) -> bool:
    """Return True if pass-through ``args`` start with
    ``<python> -m yoke_core.domain.deploy_pipeline``."""
    if len(args) < 3:
        return False
    return (
        _looks_like_python_executable(args[0])
        and args[1] == "-m"
        and args[2] == "yoke_core.domain.deploy_pipeline"
    )


def _deploy_argv(args: Sequence[str]) -> list[str]:
    """Build the underlying deploy_pipeline invocation."""
    return [
        sys.executable,
        "-m",
        "yoke_core.domain.deploy_pipeline",
        *list(args),
    ]


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="watch_deploy",
        description=(
            "Run deploy_pipeline under the shared raw+progress watcher wrapper."
        ),
        allow_abbrev=False,
    )
    parser.add_argument(
        _watch_runner.PRINT_STREAMING_PAIR_FLAG,
        dest="print_streaming_pair",
        action="store_true",
        help="Print a ready-to-paste background command + progress-tail pair "
        "and exit. Mints fresh capture paths.",
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
        help=(
            "Bare deploy_pipeline arguments. Use ``--`` to separate wrapper "
            "flags from deploy args. Do NOT include "
            "``python3 -m yoke_core.domain.deploy_pipeline``; the wrapper "
            "supplies that prefix."
        ),
    )
    return parser.parse_args(list(argv))


def _strip_separator(passthrough: list[str]) -> list[str]:
    """Drop a leading ``--`` argparse left in the REMAINDER list."""
    if passthrough and passthrough[0] == "--":
        return passthrough[1:]
    return passthrough


def _extract_print_streaming_pair(argv: list[str]) -> tuple[list[str], bool]:
    """Pull ``--print-streaming-pair`` out of any position in ``argv``.

    ``passthrough`` uses ``nargs=argparse.REMAINDER``, which means the
    flag would otherwise reach deploy_pipeline verbatim if placed after
    the ``--`` separator. Pre-extracting makes every position
    equivalent.
    """
    filtered: list[str] = []
    found = False
    for arg in argv:
        if arg == _watch_runner.PRINT_STREAMING_PAIR_FLAG:
            found = True
            continue
        filtered.append(arg)
    return filtered, found


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    raw, print_streaming_pair_flag = _extract_print_streaming_pair(raw)
    ns = _parse_args(raw)
    if print_streaming_pair_flag:
        ns.print_streaming_pair = True
    deploy_args = _strip_separator(list(ns.passthrough))

    if _is_nested_deploy_invocation(deploy_args):
        print(NESTED_DEPLOY_REJECTION_MESSAGE, file=sys.stderr)
        return 2

    if ns.print_streaming_pair:
        raw_path, progress_path = _watch_runner.mint_capture_paths(KIND)
        _watch_runner.print_streaming_pair(
            kind=KIND,
            wrapper_module=WRAPPER_MODULE,
            wrapper_args=deploy_args,
            raw_capture=raw_path,
            progress_capture=progress_path,
        )
        return 0

    if ns.raw_capture is None or ns.progress_capture is None:
        minted_raw, minted_progress = _watch_runner.mint_capture_paths(KIND)
        raw_path = ns.raw_capture or minted_raw
        progress_path = ns.progress_capture or minted_progress
    else:
        raw_path = ns.raw_capture
        progress_path = ns.progress_capture

    return _watch_runner.run_watcher(
        argv=_deploy_argv(deploy_args),
        classifier=classify_deploy_line,
        raw_capture=raw_path,
        progress_capture=progress_path,
        kind=KIND,
    )


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
