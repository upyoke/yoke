"""Watch a commit's CI runs under the shared raw+progress watcher.

Waiting on CI is a long command, and until this wrapper existed it was
the one long command agents polled by hand — a capture-and-grep pair
whose filter was authored fresh at each call site, whose paired follower
had no exit sentinel, and whose matching rules were wrong often enough to
run silently past the conclusion being waited on. The watcher family
exists so a filter is written once and owned; this is that filter for CI.

The wrapper drives
:mod:`yoke_core.domain.github_actions_commit_run_watch`, which owns ref
resolution and run matching, and classifies its lines here so a state
change reaches the operator immediately while repetitive waiting ticks
coalesce.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.tools import _watch_digest, _watch_runner
from yoke_core.tools._watch_throttle import Classification, LineClass

WRAPPER_MODULE = "yoke_core.tools.watch_ci_run"
KIND = "ci_run"
# argparse prog for a direct module invocation; the CLI adapter passes the
# ``yoke watch ci-run`` form so help reads back the command as typed.
DEFAULT_PROG = "watch_ci_run"

ENGINE_MODULE = "yoke_core.domain.github_actions_commit_run_watch"

# A watch that ends without a verdict is the failure this wrapper exists
# to make visible, so every terminal line that is not a conclusion is
# urgent rather than summary.
CI_RUN_URGENT_PREFIXES: tuple[str, ...] = (
    "Error:",
    "CI run not found:",
    "CI run timeout:",
)
CI_RUN_SUMMARY_PREFIXES: tuple[str, ...] = (
    "CI run target:",
    "CI run concluded:",
    "CI run verdict:",
)
# Elapsed seconds is the monotonic quantity a CI wait emits; handing it to
# the throttle lets repetitive waiting ticks coalesce the way a percentage
# does for a test run.
CI_RUN_POLL_RE = re.compile(
    r"^(?:CI run status:|CI run has not appeared yet).*\(elapsed: (\d+)s"
)


def classify_ci_run_line(line: str) -> Classification:
    """Classify a single output line from the commit run watch."""
    for prefix in CI_RUN_URGENT_PREFIXES:
        if line.startswith(prefix):
            return Classification(LineClass.URGENT)
    for prefix in CI_RUN_SUMMARY_PREFIXES:
        if line.startswith(prefix):
            return Classification(LineClass.SUMMARY)
    poll = CI_RUN_POLL_RE.search(line)
    if poll:
        return Classification(
            LineClass.PROGRESS, progress_value=float(poll.group(1))
        )
    return Classification(LineClass.NOISE)


def _build_ci_run_progress_pattern() -> re.Pattern[str]:
    """Compose the public union regex from the class-specific rules."""
    parts: list[str] = []
    parts.extend("^" + re.escape(p) for p in CI_RUN_URGENT_PREFIXES)
    parts.extend("^" + re.escape(p) for p in CI_RUN_SUMMARY_PREFIXES)
    parts.append(CI_RUN_POLL_RE.pattern)
    return re.compile("|".join(parts))


CI_RUN_PROGRESS_PATTERN = _build_ci_run_progress_pattern()


def _engine_argv(args: Sequence[str]) -> list[str]:
    """Build the underlying commit run watch invocation argv."""
    return [sys.executable, "-m", ENGINE_MODULE, *list(args)]


def _parse_args(
    argv: Sequence[str], prog: str = DEFAULT_PROG,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=prog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Watch every GitHub Actions run for one exact commit under the "
            "shared raw+progress watcher. Pass the ref and any commit run "
            "watch flags after `--`; with no ref, the current checkout's "
            "resolved HEAD is watched."
        ),
        epilog=(
            "Examples:\n"
            "  yoke watch ci-run\n"
            "  yoke watch ci-run -- my-branch --workflow yoke-ci\n"
            "  yoke watch ci-run --print-streaming-pair -- HEAD\n\n"
            "The ref is resolved with `git rev-parse <ref>^{commit}` and runs "
            "are matched on that exact head SHA, so an abbreviated SHA or a "
            "branch name is as precise as a full object id. `--workflow` "
            "matches the workflow's name, not the run's display title.\n\n"
            "Exit codes: 0 every run succeeded, 1 a run concluded otherwise, "
            "2 the ref does not resolve, 3 still running at the deadline, "
            "4 project GitHub auth failure, 5 no run appeared."
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
    _watch_digest.attach_flush_seconds(parser)
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
        help="Ref followed by any commit run watch flags. Use `--` to "
        "separate wrapper flags from them.",
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
    otherwise be forwarded to the engine once it appears after the ref.
    Pre-extracting makes every position equivalent.
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
    raw, flush_seconds = _watch_digest.extract_flush_seconds(raw)
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
            wrapper_options=_watch_digest.streaming_pair_options(
                flush_seconds
            ),
        )
        return 0

    raw_path, progress_path = _watch_runner.bind_capture_paths(ns, KIND)

    return _watch_runner.run_watcher(
        argv=_engine_argv(passthrough),
        classifier=classify_ci_run_line,
        raw_capture=raw_path,
        progress_capture=progress_path,
        kind=KIND,
        flush_seconds=_watch_digest.resolve_flush_seconds(
            ns, flush_seconds
        ),
    )


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
