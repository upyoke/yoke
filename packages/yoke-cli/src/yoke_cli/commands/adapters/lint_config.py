"""``yoke lint config show`` adapter (read-only enforcement-state report).

Answers "which ``.yoke/lint-config`` governs this tree, and what is
actually in force" without having to trip a guard to find out.
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


LINT_CONFIG_SHOW_USAGE = (
    "yoke lint config show [--root PATH] [--session-id S] [--json]"
)


def lint_config_show(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke lint config show",
        description=(
            "Report the resolved .yoke/lint-config, how its root was chosen, "
            "and each guard's effective mode. A declared `warn` on a protected "
            "guard is reported as clamped when it lacks the `# allow-warn` "
            "token, which is otherwise a silent no-op."
        ),
    )
    parser.add_argument(
        "--root", default=None,
        help="Report for this workspace root instead of the resolved one.",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, LINT_CONFIG_SHOW_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        result = response.result or {}
        text = result.get("text")
        if text:
            print(text, file=stdout)
        return None

    payload: Dict[str, Any] = {}
    if parsed.root is not None:
        payload["root"] = parsed.root
    # Reads .yoke/lint-config from the caller's own tree, so it must run
    # where that tree lives. A relayed call would resolve the workspace
    # root on the server filesystem and report the wrong config.
    return dispatch_and_emit(
        function_id="lint.config.show",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
        local_only=True,
    )


__all__ = [
    "LINT_CONFIG_SHOW_USAGE",
    "lint_config_show",
]
