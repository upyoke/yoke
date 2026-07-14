"""Attended, client-local source-authority cutover adapters."""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from typing import Callable, Dict, List, Tuple

from yoke_cli.commands._helpers import parse_or_usage_error


AdapterFn = Callable[[List[str]], int]
QUIESCE_USAGE = (
    "yoke source-authority quiesce {begin,status,abort,retire} "
    "--credential-file PATH [--service-stop-receipt ID] "
    "[--retirement-receipt ID] [--json]"
)
EXPORT_USAGE = (
    "yoke source-authority export --out PATH --credential-file PATH [--json]"
)


def source_authority_quiesce(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke source-authority quiesce",
        description=(
            "Attended prod-admin write-freeze boundary. begin commits an "
            "owner-only database CONNECT fence and drains existing sessions; "
            "status proves current watermarks; abort recovers write service; "
            "retire permanently disables the obsolete source login."
        ),
    )
    parser.add_argument(
        "operation", choices=("begin", "status", "abort", "retire"),
    )
    parser.add_argument("--credential-file", required=True)
    parser.add_argument("--service-stop-receipt", default=None)
    parser.add_argument("--retirement-receipt", default=None)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, QUIESCE_USAGE)
    if parsed is None:
        return 2
    if parsed.operation == "begin" and not parsed.service_stop_receipt:
        print(
            "error: begin requires --service-stop-receipt from the attended "
            "old-service stop/absence check",
            file=sys.stderr,
        )
        return 2
    if parsed.operation == "retire" and not parsed.retirement_receipt:
        print(
            "error: retire requires --retirement-receipt from the recorded "
            "retirement gates",
            file=sys.stderr,
        )
        return 2
    kwargs = {"credential_file": parsed.credential_file}
    if parsed.operation == "begin":
        kwargs["service_stop_receipt"] = parsed.service_stop_receipt
    if parsed.operation == "retire":
        kwargs["retirement_receipt"] = parsed.retirement_receipt
    return _run(parsed.operation, json_mode=parsed.json_mode, **kwargs)


def source_authority_export(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke source-authority export",
        description=(
            "Export the selected prod-db-admin universe only inside an active "
            "quiesce boundary. Receipts contain hashes and watermarks, never "
            "the resolved DSN or credentials."
        ),
    )
    parser.add_argument("--out", required=True)
    parser.add_argument("--credential-file", required=True)
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, EXPORT_USAGE)
    if parsed is None:
        return 2
    return _run(
        "export_quiesced", out=parsed.out,
        credential_file=parsed.credential_file, json_mode=parsed.json_mode,
    )


def _run(operation: str, *, json_mode: bool, **kwargs: object) -> int:
    engine = importlib.import_module("yoke_core.domain.source_authority_cutover")
    try:
        report = getattr(engine, operation)(**kwargs)
    except (OSError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if json_mode:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"source authority {report['operation'] if 'operation' in report else 'export'}")
        print(f"quiesced: {report.get('quiesced', True)}")
        authority = report.get("authority") or report.get("source_authority") or {}
        print(f"receipt: {authority.get('receipt_digest', '')}")
        if report.get("artifact"):
            print(f"artifact: {report['artifact']}")
            print(f"sha256: {report['sha256']} bytes: {report['bytes']}")
    return 0


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("source-authority", "quiesce"): source_authority_quiesce,
    ("source-authority", "export"): source_authority_export,
}
TOOL_SHAPED_USAGE = {
    "yoke source-authority quiesce": QUIESCE_USAGE,
    "yoke source-authority export": EXPORT_USAGE,
}


__all__ = ["TOOL_SHAPED_SUBCOMMANDS", "TOOL_SHAPED_USAGE"]
