"""Follow Yoke's shipped model catalog, and say when an override differs from it."""

from __future__ import annotations

import argparse
from typing import Any, List, Mapping, TextIO

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_cli.transport.human_values import write_human
from yoke_contracts.api.function_call import TargetRef

FOLLOW_SHIPPED_FUNCTION_ID = "models.follow_shipped.run"
FOLLOW_SHIPPED_USAGE = "yoke models follow-shipped [--session-id S] [--json]"
FOLLOW_SHIPPED_DESCRIPTION = (
    "Make Yoke's shipped model catalog current again, replacing an operator "
    "override. Later Yoke updates then keep the catalog current on their own. "
    "Requires an org admin; earlier revisions stay, so past session prices "
    "do not change."
)


def write_shipped_notice(result: Mapping[str, Any], stdout: TextIO) -> None:
    """Explain an operator override; servers that predate it send nothing."""
    differ = result.get("shipped_defaults_differ")
    if differ is None:
        return
    stdout.write(
        "Yoke's shipped model catalog differs from this operator-published "
        "catalog, which does not follow Yoke updates. Take Yoke's catalog with "
        "`yoke models follow-shipped`.\n"
        if differ
        else "this operator-published catalog equals Yoke's shipped catalog but "
        "will not follow future Yoke updates; `yoke models follow-shipped` "
        "follows them.\n"
    )


def write_read(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    del stderr
    result = response.result or {}
    write_human(result, stdout)
    write_shipped_notice(result, stdout)


def _write_follow(response: Any, stdout: TextIO, stderr: TextIO) -> None:
    del stderr
    result = response.result or {}
    revision = result.get("revision_id")
    if result.get("appended"):
        stdout.write(
            f"now following Yoke's shipped model catalog: revision {revision} "
            f"effective {result.get('effective_at')}\n"
        )
    else:
        stdout.write(
            f"already following Yoke's shipped model catalog (revision {revision}); "
            "nothing was published\n"
        )
    write_human({"diff": result.get("diff")}, stdout)


def models_follow_shipped(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke models follow-shipped",
        usage=FOLLOW_SHIPPED_USAGE,
        description=FOLLOW_SHIPPED_DESCRIPTION,
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, FOLLOW_SHIPPED_USAGE)
    if parsed is None:
        return 2
    return dispatch_and_emit(
        function_id=FOLLOW_SHIPPED_FUNCTION_ID,
        target=TargetRef(kind="global"),
        payload={},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=None if parsed.json_mode else _write_follow,
    )


USAGE_BY_FUNCTION_ID = {FOLLOW_SHIPPED_FUNCTION_ID: FOLLOW_SHIPPED_USAGE}

__all__ = [
    "FOLLOW_SHIPPED_USAGE",
    "USAGE_BY_FUNCTION_ID",
    "models_follow_shipped",
    "write_read",
    "write_shipped_notice",
]
