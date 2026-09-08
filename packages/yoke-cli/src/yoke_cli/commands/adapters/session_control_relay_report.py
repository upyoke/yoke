"""Machine-local recovery for one permanently rejected relay report."""

from __future__ import annotations

import argparse
import json
import sys
from typing import List

from yoke_cli.commands._helpers import parse_or_usage_error, usage_error
from yoke_contracts.session_control.teaching import FLEET_OWNERSHIP_GUIDANCE
from yoke_contracts.session_execution import is_subagent_execution


RELAY_REPORT_QUARANTINE_USAGE = (
    "yoke relay report quarantine <opaque-report-id> [--json]"
)


def _relay_state_dir():
    from yoke_harness.session_relay_schedule import relay_state_dir

    return relay_state_dir()


def relay_report_quarantine(args: List[str]) -> int:
    """Move one permanently rejected pending report into retained quarantine."""
    parser = argparse.ArgumentParser(
        prog="yoke relay report quarantine",
        description=(
            "Preserve one pending relay report after its permanent server rejection."
        ),
    )
    parser.add_argument("report_id")
    parser.add_argument("--json", dest="json_mode", action="store_true")
    parsed = parse_or_usage_error(parser, args, RELAY_REPORT_QUARANTINE_USAGE)
    if parsed is None:
        return 2
    if is_subagent_execution():
        return usage_error(FLEET_OWNERSHIP_GUIDANCE)
    try:
        from yoke_harness.session_relay_report_retry import (
            PendingReportQuarantineError,
            quarantine_pending_report,
        )
    except ModuleNotFoundError as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "code": "relay_report_runtime_unavailable",
                    "message": str(exc),
                    "recovery": "Install the yoke-harness product package.",
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    try:
        report = quarantine_pending_report(
            parsed.report_id,
            state_dir=_relay_state_dir(),
        )
    except PendingReportQuarantineError as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "code": exc.code,
                    "message": str(exc),
                    "recovery": exc.recovery,
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    except Exception as exc:
        print(
            json.dumps(
                {
                    "success": False,
                    "code": "relay_report_quarantine_failed",
                    "message": str(exc),
                    "recovery": (
                        "Run `yoke relay status --json` and inspect relay "
                        "state-directory permissions before retrying this report id."
                    ),
                },
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    recovery = (
        "The server already retained a terminal outcome; do not replay this report."
        if report.get("error_code") == "report_conflict"
        else "Correct the named contract rejection before reconstructing any report."
    )
    payload = {"success": True, "report": report, "recovery": recovery}
    if parsed.json_mode:
        print(json.dumps(payload, sort_keys=True))
    else:
        print("RELAY REPORT QUARANTINED")
        print(f"Report ID       {report['report_id']}")
        print(f"Server reason  {report['error_code']}")
        print(f"Preserved at   {report['preserved_path']}")
        print(f"SHA-256        {report['payload_sha256']}")
        print(f"Recovery       {recovery}")
    return 0


__all__ = ["RELAY_REPORT_QUARANTINE_USAGE", "relay_report_quarantine"]
