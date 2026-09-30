"""Client-local selection of the installed product's origin and channel."""

from __future__ import annotations

import argparse
import json

from yoke_cli.config import distribution

DISTRIBUTION_SET_USAGE = distribution.SELECT_COMMAND + " [--json]"


def distribution_set(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke config distribution set",
        description="Record the origin and channel used by subsequent yoke updates.",
    )
    parser.add_argument("--origin", required=True)
    parser.add_argument("--channel", required=True)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parser.parse_args(args)
    try:
        result = distribution.save(origin=parsed.origin, channel=parsed.channel)
    except distribution.DistributionError as exc:
        print(
            json.dumps({"ok": False, "error": str(exc)})
            if parsed.json_mode
            else str(exc)
        )
        return 1
    print(
        json.dumps({"ok": True, **result})
        if parsed.json_mode
        else f"Recorded Yoke distribution {result['origin']} ({result['channel']})."
    )
    return 0
