"""Report rendering, progress streaming, and exit status for ``yoke doctor run``.

Both transports end here so one command has one output contract. Human
mode prints the Markdown health report the engine entrypoint prints;
``--json`` prints the typed envelope; either way the exit status answers
"is this install healthy?" — non-zero when the run itself failed and
non-zero when it recorded a FAIL, which is the status callers have always
branched on.

Rendering and progress rendering both belong to the engine, which owns
the report layout and the two progress line shapes. Client packages must
not take a static ``yoke_core`` import, so they are loaded dynamically
here — the same boundary rule ``doctor_https_compose`` follows.
"""

from __future__ import annotations

import importlib
import json
import sys
from contextlib import AbstractContextManager
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional

from yoke_contracts.api.function_call import FunctionCallResponse

from yoke_cli.transport.dispatcher import response_to_dict


def _progress() -> Any:
    return importlib.import_module("yoke_core.engines.doctor_progress")


def stream_progress_to_stderr() -> AbstractContextManager[None]:
    """Install the per-check progress sink for one doctor run.

    Held across the whole run, whichever transport serves it: checks this
    process executes emit through the shared executor, and relayed
    verdicts are rendered from their rows through the same sink. Progress
    goes to stderr so stdout stays the report (or the JSON envelope) a
    caller parses, matching how every other long Yoke gate streams while
    it works.
    """
    return _progress().progress_to(sys.stderr)


def emit_relayed_progress(rows: Iterable[Mapping[str, Any]]) -> None:
    """Emit per-check lines for verdicts that arrived from the server.

    A relayed batch is the only place a check completes without this
    process running it, so the client renders those lines from the rows
    themselves. There is no matching ``running HC-…`` line: the roster
    lives server-side, so the next check's name is not known here until
    its verdict comes back.
    """
    _progress().emit_result_rows(rows)


def report_text(result: Mapping[str, Any]) -> str:
    """The Markdown health report for one doctor result payload."""
    render = importlib.import_module("yoke_core.engines.doctor_result_report")
    return render.report_from_result(result)


def emit_doctor_response(
    response: FunctionCallResponse,
    *,
    json_mode: bool,
    report_file: Optional[str] = None,
) -> int:
    """Print one doctor run's outcome and return its exit status."""
    result = response.result or {}
    if json_mode:
        print(json.dumps(response_to_dict(response), sort_keys=True))
    else:
        if result:
            report = report_text(result)
            print(report)
            if report_file:
                _write_report(report, report_file)
        if not response.success and response.error is not None:
            print(
                f"error ({response.error.code}): {response.error.message}",
                file=sys.stderr,
            )
            if response.error.recovery_hint:
                print(f"hint: {response.error.recovery_hint}", file=sys.stderr)
    for warning in response.warnings:
        print(
            f"warning: {warning.code} ({warning.step}): {warning.detail}",
            file=sys.stderr,
        )
    sys.stdout.flush()
    sys.stderr.flush()
    if not response.success:
        return 1
    return 1 if int(result.get("fail_count") or 0) > 0 else 0


def _write_report(report: str, report_file: str) -> None:
    out_path = Path(report_file)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report, encoding="utf-8")
    print(f"\nReport saved to: {report_file}")


__all__ = [
    "emit_doctor_response",
    "emit_relayed_progress",
    "report_text",
    "stream_progress_to_stderr",
]
