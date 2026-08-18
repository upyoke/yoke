"""CLI argv adapter for ``service-client session-offer``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

def cmd_session_offer(args: List[str]) -> int:
    """Compute frontier state and decide the next action for a session offer.

    ``--model`` is optional; falls back to ``harness_sessions.model`` lookup
    then ``hook_helpers_model.detect_model``.
    """
    parser = argparse.ArgumentParser(prog="session-offer", add_help=False)
    parser.add_argument("--executor", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", default=None)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--lane", default=None)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--step", type=int, default=1)
    parser.add_argument(
        "--supported-paths",
        default=None,
        help="Comma-separated canonical downstream paths.",
    )
    parser.add_argument(
        "--project",
        default=None,
        help=(
            "Comma-separated project ids to narrow the frontier scope "
            "(e.g. 'yoke,example-project'). Default: all registered projects."
        ),
    )

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print(
            "Usage: session-offer --executor E --provider P --workspace W "
            "[--model M] [--lane L] [--session-id S] [--step N] "
            "[--supported-paths P] [--project IDS]",
            file=sys.stderr,
        )
        return 2

    supported_paths: List[str] = [
        piece.strip()
        for piece in (parsed.supported_paths or "").split(",")
        if piece.strip()
    ]
    from yoke_core.api.service_client_sessions_offer import (
        SessionOfferCommandError,
        run_session_offer,
    )

    try:
        result = run_session_offer(
            executor=parsed.executor,
            provider=parsed.provider,
            model=parsed.model,
            workspace=parsed.workspace,
            lane=parsed.lane,
            session_id=parsed.session_id,
            step=parsed.step,
            supported_paths=supported_paths,
            project=parsed.project,
        )
        print(json.dumps(result))
        return 0
    except SessionOfferCommandError as exc:
        print(str(exc), file=sys.stderr)
        return 1


__all__ = ["cmd_session_offer"]
