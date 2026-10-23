"""HTTPS-safe adapter for configured release-pin recording."""

from __future__ import annotations
from yoke_cli.transport.human_values import write_human

import argparse
from typing import List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


RECORD_USAGE = (
    "yoke release-pin record --project NAME --environment ENV --pin VERSION "
    "[--session-id S] [--json]"
)


def release_pin_record(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="yoke release-pin record", usage=RECORD_USAGE)
    parser.add_argument(
        "--project", required=True, metavar="NAME", help="Project to record the pin for."
    )
    parser.add_argument(
        "--environment",
        required=True,
        metavar="ENV",
        help="Deploy target name declared by the project's release_pin capability.",
    )
    parser.add_argument(
        "--pin", required=True, metavar="VERSION", help="Release version to pin."
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, RECORD_USAGE)
    if parsed is None:
        return 2

    def _human_writer(response, stdout, stderr) -> None:
        write_human(response.result or {}, stdout)

    return dispatch_and_emit(
        function_id="release_pin.record",
        target=TargetRef(kind="global", project_id=parsed.project),
        payload={
            "project": parsed.project,
            "environment": parsed.environment,
            "pin": parsed.pin,
        },
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )


__all__ = ["RECORD_USAGE", "release_pin_record"]
