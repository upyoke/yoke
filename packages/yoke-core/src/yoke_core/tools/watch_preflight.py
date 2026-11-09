"""Run the fleet migration preflight under the shared watcher.

The preflight copies and converges every live database a project's migration
model declares as its fleet before a release carrying migration history. It can take minutes, so direct execution
leaves callers choosing between buffered output and a hand-authored follower
that cannot observe the watcher exit sentinel.

Use ``yoke watch preflight -- <preflight args>``. The wrapper preserves the
preflight's exit code, forces immediate Python output through the shared
runner, and emits the fleet roster, database verdicts, the fleet summary,
the receipt, and failure signatures to its progress capture.
"""

from __future__ import annotations

from yoke_core.tools import _watch_streaming_pair

from yoke_core.domain.fleet_preflight_watch import (
    KIND,
    _preflight_argv,
    classify_preflight_line,
    preflight_failure,
)

import argparse
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.domain import watch_digest as _watch_digest
from yoke_core.domain import watch_runner as _watch_runner

WRAPPER_MODULE = "yoke_core.tools.watch_preflight"
DEFAULT_PROG = "watch_preflight"

# Terminal outcomes: what the whole fleet came to, and whether the
# receipt the release gate reads was written.
# Motion: a fleet rehearsal names its artifact, rosters the cluster it
# selected from, then passes one database at a time. Every one of those
# lines is distinct content, so the digest carries them all rather than
# dropping any -- the roster in particular is the only place a reader can
# see which neighbours were left out of the fleet and why.


HELP_EPILOG = """\
``--project`` names the project whose declared migration-model fleet to
rehearse; ``--model`` defaults to its ``default_model``; ``--checkout``
names the checkout a ``named_databases`` fleet converges from (default: the
project's registered checkout). The positional
names the project's registered environment whose fleet to rehearse.
The paired admin connection is that environment's
``release.admin_connection`` setting, not a name suffix. ``--receipt-env``
names the control plane that records the receipt. ``--record-receipt``
writes the receipt the release gate reads for that environment.
One environment's receipt never satisfies another, so rehearse each
environment a release targets. Before a workflow dispatch the release gate
runs this for every project the workflow ships, including each project bound
through ``input_bindings``, at that project's own commit. The receipt lands on that environment's
own settings document under ``release.fleet_rehearsal.<model>``, so coverage is
durable state rather than telemetry that can expire.

Preflight runs from the installed package in any working directory.
Ordinary pre-release rehearsal uses the active engine (no ``--engine-wheel``).
The release wheel does not exist until after tag allocation.
``--engine-wheel`` pins an already-built artifact when you have one.

For read-only restored-source instant inspection, add
``--instant-census-output DIR --copy-budget-gib N --minimum-free-gib N``.
This skips history/convergence and release-driver writes, retains aggregate
counts/timing/sizes before cleanup, and refuses ``--record-receipt``.
Keep the output and disposable copies on the same filesystem; a budget or
free-space refusal stops its transfer and cleans up the disposable copy.

examples:
  yoke watch preflight -- --project yoke stage --record-receipt \\
      --product-sha SHA --receipt-env <control-plane>

  yoke watch preflight -- --project platform --model registry prod \\
      --record-receipt --product-sha SHA --receipt-env <control-plane>

  yoke watch preflight -- --project yoke stage \\
      --engine-wheel /path/to/yoke_core-release.whl --record-receipt \\
      --product-sha SHA --receipt-env <control-plane>

  yoke watch preflight --print-streaming-pair -- --project yoke \\
      stage --record-receipt --product-sha SHA --receipt-env <control-plane>

Copy admission is automatic for each physical local cluster/copy name through
cleanup. rehearsal_copy_busy refuses without touching the copy; retry after the
named holder or its surviving transfer child finishes. Manual database operations
outside the rehearsal kernel are not covered.

Pass bare preflight arguments after ``--``. The wrapper supplies
``python3 -m yoke_core.tools.preflight_fleet_migrations``.

When a release-surface capability contract blocks a receipt: read the
stored document with ``yoke projects capability-settings get``, then
either converge it with ``capability-settings set --base <as-read>`` or
remove it with ``capability-settings remove --base <as-read>`` when it
carries no policy. Never guess an enum value or hand-edit SQL.
"""


def _parse_args(
    argv: Sequence[str],
    prog: str = DEFAULT_PROG,
) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=prog,
        description=(
            "Run the fleet migration preflight under the shared raw+progress watcher."
        ),
        epilog=HELP_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        allow_abbrev=False,
    )
    parser.add_argument(
        _watch_runner.PRINT_STREAMING_PAIR_FLAG,
        dest="print_streaming_pair",
        action="store_true",
        help=_watch_streaming_pair.STREAMING_WAIT_HELP,
    )
    _watch_digest.attach_flush_seconds(parser)
    parser.add_argument(
        "--raw-capture",
        type=Path,
        default=None,
        help="Explicit raw capture path. Defaults under project scratch.",
    )
    parser.add_argument(
        "--progress-capture",
        type=Path,
        default=None,
        help="Explicit progress capture path. Defaults under project scratch.",
    )
    parser.add_argument(
        "passthrough",
        nargs=argparse.REMAINDER,
        help="Bare preflight arguments, separated from wrapper flags by --.",
    )
    return parser.parse_args(list(argv))


def _extract_print_streaming_pair(argv: list[str]) -> tuple[list[str], bool]:
    """Make ``--print-streaming-pair`` position-independent."""
    filtered: list[str] = []
    found = False
    for arg in argv:
        if arg == _watch_runner.PRINT_STREAMING_PAIR_FLAG:
            found = True
            continue
        filtered.append(arg)
    return filtered, found


def _strip_separator(passthrough: Sequence[str]) -> list[str]:
    args = list(passthrough)
    if args and args[0] == "--":
        args = args[1:]
    return args


def main(argv: Sequence[str] | None = None, *, prog: str = DEFAULT_PROG) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    raw, print_streaming_pair_flag = _extract_print_streaming_pair(raw)
    raw, flush_seconds = _watch_digest.extract_flush_seconds(raw)
    ns = _parse_args(raw, prog)
    if print_streaming_pair_flag:
        ns.print_streaming_pair = True
    passthrough = _strip_separator(ns.passthrough)

    if ns.print_streaming_pair:
        raw_path, progress_path = _watch_runner.mint_capture_paths(KIND)
        return _watch_streaming_pair.print_wait_mode_invocation(
            kind=KIND,
            wrapper_module=WRAPPER_MODULE,
            wrapper_args=passthrough,
            raw_capture=raw_path,
            progress_capture=progress_path,
            wrapper_options=_watch_digest.streaming_pair_options(flush_seconds),
        )

    raw_path, progress_path = _watch_runner.bind_capture_paths(ns, KIND)

    return _watch_runner.run_watcher(
        argv=_preflight_argv(passthrough),
        classifier=classify_preflight_line,
        raw_capture=raw_path,
        progress_capture=progress_path,
        kind=KIND,
        exit_metadata=lambda rc: preflight_failure(rc, raw_path),
        flush_seconds=_watch_digest.resolve_flush_seconds(ns, flush_seconds),
    )


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    raise SystemExit(main())
