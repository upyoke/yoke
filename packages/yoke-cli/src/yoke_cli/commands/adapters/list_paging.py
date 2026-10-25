"""Shared list page arguments and explicit continuation replies."""

from __future__ import annotations

import argparse
from functools import partial

from yoke_cli.commands._helpers import dispatch_and_emit
from yoke_cli.transport.human_values import write_human
from yoke_cli.transport.output_limit import page_command
from yoke_contracts.list_paging import DEFAULT_LIST_LIMIT, MAX_LIST_LIMIT


def _limit(raw: str, *, maximum: int) -> int:
    value = int(raw)
    if not 1 <= value <= maximum:
        raise argparse.ArgumentTypeError(f"pass --limit 1..{maximum}")
    return value


def _offset(raw: str) -> int:
    value = int(raw)
    if value < 0:
        raise argparse.ArgumentTypeError("pass --offset 0 or greater")
    return value


def add_page_args(
    parser: argparse.ArgumentParser,
    *,
    limit=DEFAULT_LIST_LIMIT,
    offset=0,
    page_size=DEFAULT_LIST_LIMIT,
    maximum=MAX_LIST_LIMIT,
) -> None:
    parser.add_argument(
        "--limit",
        type=partial(_limit, maximum=maximum),
        default=limit,
        metavar="N",
        help=f"Most rows per page (default: {limit or page_size}; maximum: {maximum}).",
    )
    parser.add_argument(
        "--offset",
        type=_offset,
        default=offset,
        metavar="N",
        help="Rows to skip before the first returned row (default: 0).",
    )
    parser.epilog = (parser.epilog or "") + (
        "\nKeep the same filters and follow the printed next-page command; "
        "--json returns complete page fields and next_offset."
    )


def dispatch_list(*, parsed, **kwargs) -> int:
    kwargs["payload"] = {
        **kwargs.get("payload", {}),
        **{
            key: getattr(parsed, key)
            for key in ("limit", "offset")
            if getattr(parsed, key) is not None
        },
    }
    writer = kwargs.pop("human_writer", None)

    def write(response, stdout, stderr):
        if writer is None:
            write_human(response.result or {}, stdout)
        else:
            writer(response, stdout, stderr)
        next_offset = (response.result or {}).get("next_offset")
        if next_offset is not None:
            command = page_command(next_offset) or f"--offset {next_offset}"
            print(f"More rows. Next page: {command}", file=stdout)

    return dispatch_and_emit(**kwargs, human_writer=write)
