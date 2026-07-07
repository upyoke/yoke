"""Session inspection and admin command handlers.

Covers:
- ``harness-capabilities`` — resolve shared capabilities plus manifest limits
- ``clean-stale-sessions`` — unified stale-session cleanup
"""

from __future__ import annotations

import json
import os
import sys

from yoke_core.api.service_client_shared import (
    _get_db_readwrite,
    domain_clean_stale,
)


def cmd_harness_capabilities(args: list[str]) -> int:
    """Resolve shared harness capabilities keyed by executor.

    Usage: harness-capabilities --executor E --workspace W

    Prints JSON with downstream_paths and source.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="harness-capabilities", add_help=False)
    parser.add_argument("--executor", required=True)
    parser.add_argument("--workspace", required=True)

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print("Usage: harness-capabilities --executor E --workspace W", file=sys.stderr)
        return 2

    from yoke_core.domain.sessions import resolve_harness_capabilities
    result = resolve_harness_capabilities(parsed.executor, parsed.workspace)
    print(json.dumps(result))
    return 0


def cmd_clean_stale_sessions(args: list[str]) -> int:
    """Unified stale-session cleanup: never-engaged, heartbeat-stale, progress-stale.

    Usage: clean-stale-sessions [--threshold-minutes N] [--progress-threshold-minutes N]

    Reads ``session_stale_ttl_minutes`` from machine settings as the default
    when ``--threshold-minutes`` is not supplied (default 20).
    Codex sessions automatically use a longer reclaim window driven by
    ``sessions.EXECUTOR_STALE_TTL_OVERRIDES_MINUTES`` so between-turn idle does
    not cause spurious reclaims.

    Prints JSON with categorized results including ``skipped_between_turns``.
    """
    import argparse

    from yoke_core.domain.sessions import (
        DEFAULT_PROGRESS_THRESHOLD_MINUTES,
        DEFAULT_STALE_THRESHOLD_MINUTES,
    )

    parser = argparse.ArgumentParser(prog="clean-stale-sessions", add_help=False)
    parser.add_argument("--threshold-minutes", type=int, default=None)
    parser.add_argument(
        "--progress-threshold-minutes",
        type=int,
        default=DEFAULT_PROGRESS_THRESHOLD_MINUTES,
    )

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print(
            "Usage: clean-stale-sessions [--threshold-minutes N] [--progress-threshold-minutes N]",
            file=sys.stderr,
        )
        return 2

    threshold = parsed.threshold_minutes
    if threshold is None:
        from yoke_core.api.service_client_shared import _repo_root
        from yoke_core.domain import runtime_settings

        config_path = os.path.join(_repo_root, "data", "config")
        threshold = runtime_settings.get_int(
            "session_stale_ttl_minutes",
            DEFAULT_STALE_THRESHOLD_MINUTES,
            config_path=config_path,
        )

    conn = _get_db_readwrite()
    try:
        result = domain_clean_stale(
            conn, threshold, parsed.progress_threshold_minutes,
        )
        print(json.dumps({"success": True, "threshold_minutes": threshold, **result}))
        return 0
    finally:
        conn.close()


__all__ = [
    "cmd_harness_capabilities",
    "cmd_clean_stale_sessions",
]
