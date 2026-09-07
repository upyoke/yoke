"""Operator refresh of this machine's native model availability."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from yoke_cli.commands._helpers import parse_or_usage_error
from yoke_cli.commands.adapters.session_control_launch_output import (
    write_relay_model_summary,
)


RELAY_PROBE_MODELS_USAGE = "yoke relay probe-models [--surface S] [--json]"
#: A surface Yoke declares no adapter for, and one serving its last known
#: models after a failed attempt, are both answers. Only a surface Yoke tried
#: and could not read at all makes this command exit non-zero.
_ANSWERED_STATUSES = frozenset({"ok", "stale", "unsupported"})


def relay_probe_models(args: List[str]) -> int:
    """Refresh this machine's native model availability now, past the cadence."""
    from yoke_contracts.session_control.native_models import NATIVE_MODEL_SURFACES
    from yoke_harness.session_relay_native_models import observe_native_models

    parser = argparse.ArgumentParser(
        prog="yoke relay probe-models", description=RELAY_PROBE_MODELS_USAGE
    )
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parser.add_argument("--surface", choices=NATIVE_MODEL_SURFACES)
    parsed = parse_or_usage_error(parser, args, RELAY_PROBE_MODELS_USAGE)
    if parsed is None:
        return 2
    selected = (parsed.surface,) if parsed.surface else None
    readings = observe_native_models(selected, force=True)
    if parsed.json_mode:
        print(json.dumps({"surfaces": readings}, sort_keys=True))
    else:
        write_relay_model_summary(readings, sys.stdout)
    return (
        0
        if all(
            reading.get("status") in _ANSWERED_STATUSES
            for reading in readings.values()
        )
        else 1
    )


__all__ = ["RELAY_PROBE_MODELS_USAGE", "relay_probe_models"]
