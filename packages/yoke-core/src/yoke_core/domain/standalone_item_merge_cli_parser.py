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
            "Wait for queue landing inline, instead of the enqueue-and-"
            "re-enter handoff. A launched headless worker uses this: it "
            "cannot be prompted on the landing-complete message. Red "
            "required checks return immediately; the poll budget is for "
            "pending checks or trains.",
        ),
    )
    for flag, help_text in boolean_options:
        parser.add_argument(flag, action="store_true", help=help_text)
    parser.add_argument("--json", action="store_true")
    return parser


__all__ = ["build_parser"]
