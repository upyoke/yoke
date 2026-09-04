"""The argument surface of ``yoke merge item``."""

from __future__ import annotations

import argparse
import os

from yoke_contracts.dash_evidence_status import status_argument_kwargs


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="yoke merge item")
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
        ("--skip-status", "Merge without changing lifecycle status."),
        ("--pr", "Merge through a pull request."),
        (
            "--wait",
            "Wait for queue landing inline instead of returning "
            "landing_pending. Invoke through the reachability-routed watch "
            "merge wrapper: no or unknown wake route stays in-turn, while "
            "only a verified route may release to its subscription. Each "
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
