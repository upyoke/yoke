"""CLI argv adapter for ``service-client session-offer``."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List


def cmd_session_offer(args: List[str]) -> int:
    """Compute frontier state and decide the next action for a session offer.

    Takes only what the session row cannot answer: which session is asking,
    the chain step, an optional project-scope narrowing, and an optional
    operator lane override. Executor, provider, model, and workspace are read
    from the row registration wrote.
    """
    parser = argparse.ArgumentParser(prog="session-offer", add_help=False)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--step", type=int, default=1)
    parser.add_argument(
        "--lane",
        default=None,
        help=(
            "Deliberate operator lane override; recorded as "
            "SessionOfferLaneOverrideApplied. Autonomous loops pass nothing."
        ),
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
            "Usage: session-offer [--session-id S] [--step N] [--lane L] "
            "[--project IDS]",
            file=sys.stderr,
        )
        return 2

    from yoke_core.api.service_client_shared import _resolve_session_id
    from yoke_core.api.service_client_sessions_offer import (
        SessionOfferCommandError,
        run_session_offer,
    )

    session_id = _resolve_session_id(parsed.session_id)

    try:
        result = run_session_offer(
            session_id=session_id,
            step=parsed.step,
            lane=parsed.lane,
            project=parsed.project,
        )
        print(json.dumps(result))
        return 0
    except SessionOfferCommandError as exc:
        print(str(exc), file=sys.stderr)
        return 1


__all__ = ["cmd_session_offer"]
