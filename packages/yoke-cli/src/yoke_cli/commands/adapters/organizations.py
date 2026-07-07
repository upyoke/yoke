"""``yoke organizations ...`` read adapters.

Function ids handled here:

* ``organizations.get`` — read the org identity card (slug, name,
  created_at). Default reads the universe's identity card; ``--slug``
  addresses a specific org on a multi-org instance.
"""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict, List

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    dispatch_and_emit,
    parse_or_usage_error,
)
from yoke_contracts.api.function_call import TargetRef


__all__ = ["organizations_get", "ORGANIZATIONS_GET_USAGE"]


ORGANIZATIONS_GET_USAGE = (
    "yoke organizations get [--slug SLUG] [--session-id S] [--json]"
)


def organizations_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke organizations get",
        description=(
            "Read the org identity card: slug, name, created_at. Without "
            "--slug this is the universe's identity card (the single org a "
            "local universe carries); --slug addresses a specific org."
        ),
    )
    parser.add_argument("--slug", default=None,
                        help="Org slug (default: the universe's identity card).")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ORGANIZATIONS_GET_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.slug:
        payload["slug"] = parsed.slug

    def _human_writer(response, stdout, stderr) -> None:
        if not response.success:
            return None
        print(json.dumps(response.result or {}, sort_keys=True), file=stdout)
        return None

    return dispatch_and_emit(
        function_id="organizations.get",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        human_writer=_human_writer,
    )
