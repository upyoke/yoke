"""The argument surface of ``yoke merge item``."""

from __future__ import annotations

import argparse
import os

from yoke_contracts.dash_evidence_status import status_argument_kwargs


#: Why this command is the whole close-out surface, and what it does at a
#: release wait. Read as ``yoke merge item --help``; the skills carry the one
#: short recipe and point here.
_EPILOG = """\
Close-out routes
----------------
This is the ONE agent-facing close-out for a merging item. It merges the lane
and records the evidence in the same call, so `--result` and `--verification`
belong on it even when the merge queue already landed the branch. Do not
substitute an internal done engine: `yoke lifecycle transition --to done` and
`done-transition --skip-deploy` cannot restore the work claim close-out needs,
and `--skip-deploy` records a selected-flow delivery as out-of-band, which is a
false record and is refused when the item's flow already has a succeeded run
covering its merge.

Which close-out applies depends on what the item's pinned deployment flow still
owes, and the envelope says which one happened -- read `status` and the
`release_wait` block rather than assuming:

  * Flow discharges delivery at the merge (no target tier): the close-out runs
    every declared stage through to `done` in this one call. Nothing else is
    owed.
  * Flow still owes a delivery: the close-out lands the item at that flow's
    release wait, KEEPS the work claim and lane, and parks this session on the
    wait. That is a completed merge and an unfinished item. Do not release the
    claim, do not end the session, and do not start a deployment run to move it
    -- the steering seat batches deliveries. Report what landed, say you are
    waiting on delivery, and stop deliberately.

At the release wait, the deployment wake re-enters the owner: to run item QA,
when that QA is accepted, or when delivery clears. If it asks for
item QA, credit it with the stage-scoped form -- a stage credits only the
requirements bound to its own name, and an item-scoped stage needs the member
too, so the run-wide form is refused rather than recording a pass the stage
ignores:

  yoke qa plan run --deployment-run-id RUN --stage STAGE --member PREFIX-N --project P

Add `--plan PLAN` only when the wake says the stage names no cases; a stage
already naming its own refuses it.

Then re-run this exact command with `--result` and `--verification` to finish
the close-out. Never poll GitHub or the run instead of the wake.

Queue landing
-------------
A relay-launched session always arms the landing and returns
`landing_pending=true` with the pull request named. That is the handoff, not a
failure: stop, and re-run this same command when the landing notice arrives.
It rejoins by exact commit rather than dispatching a second suite.
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yoke merge item",
        description=(
            "Merge one item's lane and record its close-out evidence in the "
            "same call."
        ),
        epilog=_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("item")
    parser.add_argument("--project")
    parser.add_argument("--target", default="", help="Override the base branch.")
    parser.add_argument("--session-id", default=os.environ.get("YOKE_SESSION_ID", ""))
    parser.add_argument(
        "--result",
        default="",
        help="What changed or was learned. Required to close a Dash item, "
        "including when the merge queue already landed the branch.",
    )
    parser.add_argument(
        "--verification",
        default="",
        help="Verification evidence. Required with --result to close a Dash "
        "item; do not substitute `yoke lifecycle transition --to done`.",
    )
    parser.add_argument("--verification-status", **status_argument_kwargs())
    boolean_options = (
        ("--no-changes", "Record a verified no-change result."),
        (
            "--skip-status",
            "Merge without changing lifecycle status. Admission still "
            "requires the item to have reached the review stage its "
            "pinned workflow declares.",
        ),
        ("--pr", "Merge through a pull request."),
        (
            "--wait",
            "Wait for queue landing inline instead of returning "
            "landing_pending. Ignored for a relay-launched session, which "
            "always arms and returns: a headless command cannot outlive the "
            "landing, and the landing notice wakes it for close-out. Every "
            "other caller invokes this through the wake-routed watch "
            "merge wrapper, whose --print-streaming-pair prints the shape "
            "and merges nothing: no or unverified idle wake gets one "
            "foreground command to hold open, while only a native "
            "idle-wake primitive may release to its subscription. Each "
            "cadence reads the durable server record through "
            "merge_queue.landing.observe, without worker gh/git polling. "
            "Red required checks return immediately; pending checks or "
            "trains spend the record-wait budget, and a stale record names "
            "its last refresh and recovery.",
        ),
    )
    for flag, help_text in boolean_options:
        parser.add_argument(flag, action="store_true", help=help_text)
    parser.add_argument("--json", action="store_true")
    return parser


__all__ = ["build_parser"]
