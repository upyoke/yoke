"""Command-line parsing for deployment pipeline execution."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from yoke_cli.commands.adapters.deployment_execution_authority import (
    self_deploy_door,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deploy-pipeline",
        description="Deployment pipeline orchestrator",
    )
    parser.add_argument("primary_arg", help="run-ID")
    parser.add_argument("--timeout", type=int, default=30, help="Timeout in minutes")
    parser.add_argument("--from-stage", default="", help="Resume from this stage")
    parser.add_argument("--fresh", action="store_true", help="Skip existing-run search")
    parser.add_argument(
        "--product-repo-path",
        default="",
        help="Pinned product checkout for an itemless environment deploy",
    )
    parser.add_argument(
        "--image-tag",
        default="",
        help="Explicit core image tag for item-less environment deploys",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    runner: Callable[..., int] | None = None,
) -> int:
    if runner is None:
        from yoke_core.domain.deploy_pipeline import run_pipeline

        runner = run_pipeline
    args = _build_parser().parse_args(argv)
    # The engine owns its door: a driver started by any CLI, older ones
    # included, holds the self-deploy declaration on a *-db-admin door.
    refusal, door = self_deploy_door(args.primary_arg)
    if refusal:
        print(f"error: {refusal}", file=sys.stderr)
        return 2
    with door:
        return runner(
            args.primary_arg,
            timeout_min=args.timeout,
            from_stage=args.from_stage,
            fresh=args.fresh,
            image_tag=args.image_tag,
            product_repo_path=args.product_repo_path,
        )


__all__ = ["main"]
