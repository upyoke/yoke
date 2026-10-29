"""Size the selection a dispatch will run, and publish its fan-out.

The workflow cannot ask for a matrix and a split separately without risking
the trap :mod:`yoke_core.tools.ci_shards` describes: a matrix of four jobs
against ``--splits 8`` runs half the work and still reports green, because
every job passes the slice it was handed. So this module answers both from
one sizing pass over one selection, and the workflow reads the fan-out and
the split count back as two outputs of the same job.

Sizing is all it does: no Postgres, no test run. The selection is a function
of ``(base_sha, head_sha)`` and the timing profile the job refreshed, so the
plan costs a checkout and an install rather than a share of the suite.

A selection full CI answers as fast is refused here, before any shard
starts, with the reason the shared estimate names. The dispatcher refuses
the same selection before dispatching; this catches a hand trigger and a
selection the refreshed profile sizes larger than the committed one did.
"""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path
from typing import Sequence

from yoke_core.tools.ci_selection_inputs import (
    EXIT_USAGE,
    add_dispatch_arguments,
    checkout_mismatch,
    positional_args,
    selection_paths,
)
from yoke_core.tools.ci_shard_sizing import SelectionEstimate, selection_estimate
from yoke_core.tools.ci_shards import emit_output_lines, shard_list

#: The selection is full CI's work; no shard was planned.
EXIT_FULL_CI = 3

#: Where the full suite runs instead, phrased for any project.
FULL_CI_RECOVERY = (
    "run the item's full QA case instead: `yoke qa requirement list --item "
    "PREFIX-N`, then `yoke qa case run --requirement-id <id>`; "
    "with no case, merge-queue CI runs the full suite"
)


def selection_targets(
    root: Path, *, base_sha: str, passthrough: Sequence[str]
) -> list[str]:
    """Everything the dispatched run will collect from, however it was named.

    The impacted selection and the dispatch's own positional arguments both
    reach pytest, so both are sized: dropping either would plan for less work
    than the shards are about to do.
    """
    targets = list(selection_paths(root, base_sha) or []) if base_sha else []
    targets.extend(positional_args(passthrough))
    return targets


def plan_lines(count: int) -> list[str]:
    """The fan-out and the split count, from the one plan that sized both."""
    shards = ",".join(str(shard) for shard in shard_list(count))
    return [f"shards=[{shards}]", f"splits={count}"]


def plan(
    root: Path, *, base_sha: str, passthrough: Sequence[str]
) -> SelectionEstimate:
    """Size this dispatch's selection against the whole suite."""
    targets = selection_targets(root, base_sha=base_sha, passthrough=passthrough)
    estimate = selection_estimate(root, targets)
    print(
        f"ci_selection_plan: targets={len(targets)} {estimate.summary()}",
        flush=True,
    )
    return estimate


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ci_selection_plan",
        description=(
            "Publish the shard fan-out and split count for the selection "
            "(base_sha, head_sha) names."
        ),
    )
    add_dispatch_arguments(parser)
    parser.add_argument(
        "--write-github-output",
        action="store_true",
        help="Append the plan to $GITHUB_OUTPUT instead of stdout.",
    )
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    root = Path(args.root or Path.cwd()).resolve()
    mismatch = checkout_mismatch(root, args.head_sha.strip())
    if mismatch:
        print(mismatch, flush=True)
        return EXIT_USAGE
    estimate = plan(
        root,
        base_sha=args.base_sha.strip(),
        passthrough=shlex.split(args.pytest_args),
    )
    if reason := estimate.full_ci_reason:
        print(
            f"Error: ci_selection_plan: {reason}; no selection shard runs. "
            f"Full CI answers this change: {FULL_CI_RECOVERY}.",
            flush=True,
        )
        return EXIT_FULL_CI
    emit_output_lines(
        plan_lines(estimate.shards), write_github_output=args.write_github_output
    )
    return 0


__all__ = [
    "EXIT_FULL_CI",
    "FULL_CI_RECOVERY",
    "main",
    "plan",
    "plan_lines",
    "selection_targets",
]


if __name__ == "__main__":
    raise SystemExit(main())
