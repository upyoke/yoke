"""Run a deployment pipeline under the shared raw+progress watcher.

A hosted deploy is the longest command an operator runs — the release
bridge alone polls a GitHub Actions workflow for ten to twenty minutes —
and it was the last long command with no wrapper, so every invocation
hand-authored a capture-and-grep pair whose paired Monitor had no exit
sentinel and kept running after the deploy finished.

The wrapper drives the same module the ``yoke deployment-runs execute``
adapter drives, and repeats that adapter's owner-only connection guard:
the run row lives on a control-plane ``-db-admin`` connection, and
reaching the engine through this wrapper must not become a way around
the check that says so.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Sequence

from yoke_contracts.machine_config.schema import (
    DB_ADMIN_ENV_SUFFIX,
    ENV_OVERRIDE,
)
from yoke_contracts.deployment_itemless_teaching import (
    ITEMLESS_RELEASE_RECIPE,
    WATCH_DEPLOY_DESCRIPTION,
)
from yoke_core.tools import _watch_runner
from yoke_core.tools._watch_throttle import Classification, LineClass

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
)
DEPLOY_SUMMARY_PREFIXES: tuple[str, ...] = (
    "--- Stage:",
    "Pipeline complete",
    "Deployment authority:",
)
# Indented by the pipeline, so these match anywhere on the line rather
# than at its start.
DEPLOY_SUMMARY_RE = re.compile(
    r"(Workflow run ID:|completed successfully|has no member items)"
)
# A relay that cannot answer is the failure mode that cost a release most
# of its wall clock, so it is urgent rather than progress even though the
# pipeline keeps retrying past it.
DEPLOY_RELAY_UNAVAILABLE_RE = re.compile(
    r"status relay is temporarily unavailable"
)
DEPLOY_POLL_RE = re.compile(r"Workflow status: \S+ \(elapsed: (\d+)s")


def classify_deploy_line(line: str) -> Classification:
    """Classify a single output line from the deployment pipeline."""
    for prefix in DEPLOY_URGENT_PREFIXES:
        if line.startswith(prefix):
            return Classification(LineClass.URGENT)
    if DEPLOY_RELAY_UNAVAILABLE_RE.search(line):
        return Classification(LineClass.URGENT)
    for prefix in DEPLOY_SUMMARY_PREFIXES:
        if line.startswith(prefix):
            return Classification(LineClass.SUMMARY)
    if DEPLOY_SUMMARY_RE.search(line):
        return Classification(LineClass.SUMMARY)
    poll = DEPLOY_POLL_RE.search(line)
    if poll:
        # Elapsed seconds is the only monotonic quantity a deploy emits;
        # handing it to the throttle lets repetitive polls coalesce the
        # way a percentage does for a test run.
        return Classification(
            LineClass.PROGRESS, progress_value=float(poll.group(1))
        )
    return Classification(LineClass.NOISE)


def _build_deploy_progress_pattern() -> re.Pattern[str]:
    """Compose the public union regex from the class-specific regexes.

    Prefix alternatives are anchored to line start so a quoted ``Error:``
    inside a run summary does not read as a banner.
    """
    parts: list[str] = []
    parts.extend("^" + re.escape(p) for p in DEPLOY_URGENT_PREFIXES)
    parts.extend("^" + re.escape(p) for p in DEPLOY_SUMMARY_PREFIXES)
    parts.append(DEPLOY_SUMMARY_RE.pattern)
    parts.append(DEPLOY_RELAY_UNAVAILABLE_RE.pattern)
    parts.append(DEPLOY_POLL_RE.pattern)
    return re.compile("|".join(parts))


DEPLOY_PROGRESS_PATTERN = _build_deploy_progress_pattern()


def owner_only_connection_error() -> str | None:
    """Refusal text when the active env is not an owner-only connection.

    Mirrors the ``yoke deployment-runs execute`` adapter: the run row is
    readable only through the control plane's ``-db-admin`` connection, and
    a wrapper that skipped this would turn into the unguarded path.
    """
    active_env = os.environ.get(ENV_OVERRIDE, "").strip()
    if active_env.endswith(DB_ADMIN_ENV_SUFFIX):
        return None
    return (
        "watch_deploy: deployment execution requires an explicit owner-only "
        "connection, for example `yoke --env prod-db-admin watch deploy -- "
        "RUN-ID`. --env names the CONTROL-PLANE holding the run row, not the "
        "environment being deployed to."
    )


def _engine_argv(args: Sequence[str]) -> list[str]:
    """Build the underlying pipeline invocation argv."""
    return [sys.executable, "-m", ENGINE_MODULE, *list(args)]


def _parse_args(
    argv: Sequence[str], prog: str = DEFAULT_PROG,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=prog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=WATCH_DEPLOY_DESCRIPTION,
        epilog=ITEMLESS_RELEASE_RECIPE,
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


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    raw, print_streaming_pair_flag = _extract_print_streaming_pair(raw)
    ns = _parse_args(raw, prog)
    if print_streaming_pair_flag:
        ns.print_streaming_pair = True
    passthrough = _strip_separator(list(ns.passthrough))

    if ns.print_streaming_pair:
        raw_path, progress_path = _watch_runner.mint_capture_paths(KIND)
        _watch_runner.print_streaming_pair(
            kind=KIND,
            wrapper_module=WRAPPER_MODULE,
            wrapper_args=passthrough,
            raw_capture=raw_path,
            progress_capture=progress_path,
        )
        return 0

    refusal = owner_only_connection_error()
    if refusal is not None:
        sys.stderr.write(refusal + "\n")
        return 2

    if not passthrough:
        sys.stderr.write("watch_deploy: missing run id\n")
        return 2

    raw_path, progress_path = _watch_runner.bind_capture_paths(ns, KIND)

    return _watch_runner.run_watcher(
        argv=_engine_argv(passthrough),
        classifier=classify_deploy_line,
        raw_capture=raw_path,
        progress_capture=progress_path,
        kind=KIND,
    )


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
