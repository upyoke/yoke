"""Parse the installed fleet rehearsal command's project and artifact inputs."""

from __future__ import annotations

import argparse
import os
from typing import Sequence


def parse(args: Sequence[str]) -> argparse.Namespace:
    """Separate project, model and receipt flags from fleet operands."""
    parser = argparse.ArgumentParser(prog="yoke watch preflight --", add_help=False)
    parser.add_argument(
        "--run-id",
        default=os.environ.get("DEPLOYMENT_RUN_ID", ""),
        help="Deployment run whose preparation timings this rehearsal records.",
    )
    parser.add_argument(
        "--project", default="", help="Project whose declared fleet to rehearse."
    )
    parser.add_argument(
        "--model",
        default="",
        help="Migration model; defaults to the project's default_model.",
    )
    parser.add_argument(
        "--checkout", default="", help="Checkout a named-database fleet converges from."
    )
    parser.add_argument(
        "--record-receipt",
        action="store_true",
        help="Record passing whole-fleet coverage on the named control plane.",
    )
    parser.add_argument(
        "--product-sha",
        default="",
        help="Exact product source commit covered by the receipt.",
    )
    parser.add_argument(
        "--receipt-env",
        default="",
        help="Control-plane connection that stores the receipt.",
    )
    parser.add_argument(
        "--engine-wheel",
        default="",
        help="Already-built engine wheel to rehearse instead of the active engine.",
    )
    parser.add_argument(
        "--instant-census-output",
        default="",
        help="Retain restored-source diagnostic counts here; cannot record a receipt.",
    )
    parser.add_argument(
        "--copy-budget-gib",
        type=int,
        default=0,
        help="Maximum disposable-copy size in GiB for instant census.",
    )
    parser.add_argument(
        "--minimum-free-gib",
        type=int,
        default=0,
        help="Minimum remaining free GiB for instant census.",
    )
    parser.add_argument(
        "operands",
        nargs="*",
        help="Registered project environment, then optional diagnostic database names.",
    )
    parsed, unknown = parser.parse_known_args(args)
    if unknown:
        raise ValueError(f"unrecognized arguments: {' '.join(unknown)}")
    return parsed
