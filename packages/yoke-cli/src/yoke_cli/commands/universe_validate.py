"""First-class ``yoke universe validate`` client-local adapter."""

from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands._helpers import parse_or_usage_error


AdapterFn = Callable[[List[str]], int]
VALIDATION_DSN_ENV = "YOKE_PG_DSN_VALIDATION"
ROUNDTRIP_CONFIRM_ENV = "YOKE_UNIVERSE_VALIDATION_DISPOSABLE"
VALIDATE_USAGE = (
    "yoke universe validate ARCHIVE [--roundtrip] [--json] [source-dev/admin]"
)


def universe_validate(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke universe validate",
        description=(
            "Validate a portable universe archive before upload. The default "
            "runs bounded format and catalog checks without a database. "
            "--roundtrip additionally restores into the explicitly disposable "
            f"database named by {VALIDATION_DSN_ENV}; it is a source-dev/admin "
            "release and migration rehearsal surface. The destructive scratch "
            f"restore also requires {ROUNDTRIP_CONFIRM_ENV}=1."
        ),
    )
    parser.add_argument("archive")
    parser.add_argument("--roundtrip", action="store_true")
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, VALIDATE_USAGE)
    if parsed is None:
        return 2
    try:
        engine = importlib.import_module(
            "yoke_core.domain.universe_archive_validation"
        )
        if parsed.roundtrip and os.environ.get(ROUNDTRIP_CONFIRM_ENV) != "1":
            raise RuntimeError(
                f"set {ROUNDTRIP_CONFIRM_ENV}=1 to confirm the validation "
                "database is disposable"
            )
        report = (
            engine.validate_archive_roundtrip(
                parsed.archive,
                os.environ.get(VALIDATION_DSN_ENV, ""),
            )
            if parsed.roundtrip
            else engine.inspect_archive(parsed.archive)
        )
    except (ModuleNotFoundError, OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if parsed.json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"universe archive valid: {report['archive']}")
        print(
            f"bytes: {report['bytes']} table entries: "
            f"{report['table_entries']}"
        )
        if report.get("roundtrip"):
            print(
                f"round-trip: valid org={report['organization']} "
                f"schema={report['schema_fingerprint']}"
            )
    return 0


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("universe", "validate"): universe_validate,
}
TOOL_SHAPED_USAGE = {"yoke universe validate": VALIDATE_USAGE}


__all__ = [
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "ROUNDTRIP_CONFIRM_ENV",
    "universe_validate",
]
