"""Lease-authorized window listing, focus, click, typing and reading for walkers."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Optional

from yoke_contracts.desktop_input import (
    ACTIONS,
    MAX_TEXT_CHARACTERS,
    MAX_WAIT_SECONDS,
    DesktopInputRefused,
    validate_request,
)
from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_contracts.machine_qa_result_safety import (
    ensure_secret_free_result,
    redact_machine_qa_value,
)
from yoke_contracts.refusal_recovery import compose_refusal

from yoke_core.domain.agent_mission_host_command_cli import (
    add_mission_subject_arguments,
    resolve_mission_contract,
)

PROG = "yoke qa mission desktop"


def execute_agent_mission_desktop(
    raw_contract: dict[str, Any], request: dict[str, Any]
) -> dict[str, Any]:
    """Run one desktop action on the leased host and return its redacted result."""
    from yoke_core.domain.machine_qa_execution_contract import (
        HostControlExecutionContract,
    )
    from yoke_core.domain.machine_qa_local_execution import (
        _execution,
        _mission_contract,
    )

    if raw_contract.get("operation") == "host_command":
        contract = HostControlExecutionContract.model_validate(raw_contract)
    else:
        contract = _mission_contract(raw_contract)
    execution = _execution(contract)
    drive = getattr(execution.control, "drive_desktop", None)
    if drive is None:
        raise DesktopInputRefused(
            "desktop_input_unsupported_os",
            f"{contract.settings.get('os')} Test Machines have no desktop input verb",
            "On macOS drive apps with host-command --gui-session osascript "
            "(System Events); on Linux with host-command --gui-session xdotool",
        )
    secrets = tuple(execution.material.secrets.values())
    outcome = drive(request, secrets=secrets)
    result = {
        "ok": bool(outcome.ok),
        "error_code": outcome.error_code,
        **dict(outcome.evidence),
    }
    redacted = redact_machine_qa_value(result, secrets)
    ensure_secret_free_result(redacted)
    return redacted


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "List, focus, click, type into, press keys in, or read any window on "
            "an awaiting mission's native Windows Test Machine desktop. It runs "
            "in the logged-on test user's session; no RDP client or Windows App."
        ),
        epilog=(
            "Actions:\n"
            "  windows   list top-level windows (handle, title, process, pid, bounds, foreground)\n"
            "  focus     bring the target window to the foreground and verify it\n"
            "  click     click --x/--y (window-relative pixels) or an element selector\n"
            "  type      type the text piped on stdin with --text-stdin into the focused control,\n"
            "            or into the element a selector names (plain text only)\n"
            "  keys      press chords, e.g. --keys 'ctrl+l', --keys 'enter', --keys 'ctrl+a backspace'\n"
            "  read      print an element's name, value and text\n"
            "Target a window with --title SUBSTRING, --process NAME or --handle HANDLE.\n"
            "Select an element with --name (exact), --automation-id and --control-type\n"
            "(UI Automation names such as Button, Edit, Document); when several match,\n"
            "the refusal lists them and --index N picks the Nth. An option the action\n"
            "does not use is refused, never ignored.\n"
            "Every action, refusals included, prints one JSON object with ok, and on a\n"
            "refusal error_code, detail and recovery; a refusal also names itself on\n"
            "stderr and exits 1. Typed text is reported only as its length, and secrets\n"
            "or credential-shaped text are refused. Launch apps with\n"
            "`yoke qa mission host-command --gui-session`; see the result with\n"
            "`yoke test-machine screenshot`."
        ),
    )
    add_mission_subject_arguments(parser)
    parser.add_argument(
        "--test-machine",
        metavar="TEST_MACHINE",
        help="Declared case host to drive; defaults to the retained driver host.",
    )
    parser.add_argument("action", choices=ACTIONS)
    parser.add_argument("--title", help="Case-insensitive window title substring.")
    parser.add_argument("--process", help="Process name, e.g. Codex or claude.exe.")
    parser.add_argument("--handle", help="Window handle printed by `windows`.")
    parser.add_argument("--name", help="UI Automation element name (exact, any case).")
    parser.add_argument("--automation-id", dest="automation_id")
    parser.add_argument("--control-type", dest="control_type")
    parser.add_argument(
        "--index",
        type=int,
        help="Pick the Nth match (from 1) when an element selector is ambiguous.",
    )
    parser.add_argument("--x", type=int, help="Pixels from the window's left edge.")
    parser.add_argument("--y", type=int, help="Pixels from the window's top edge.")
    parser.add_argument("--button", choices=("left", "right"), help="Default left.")
    parser.add_argument("--double", action="store_true", help="Double-click.")
    parser.add_argument("--keys", help="Space-separated key chords.")
    parser.add_argument(
        "--text-stdin",
        action="store_true",
        help=f"Read the text to type from stdin (at most {MAX_TEXT_CHARACTERS} characters).",
    )
    parser.add_argument(
        "--wait-seconds",
        type=int,
        default=5,
        help=f"Seconds to wait for the window or element to appear (0..{MAX_WAIT_SECONDS}, default 5).",
    )
    return parser


def _refused(code: str, detail: str, recovery: str) -> dict[str, Any]:
    return {"ok": False, "error_code": code, "detail": detail, "recovery": recovery}


def _finish(parsed: argparse.Namespace, result: dict[str, Any]) -> int:
    """Print every outcome as one JSON object; a refusal also names itself on stderr."""
    payload = {
        "execution_id": parsed.execution_id,
        "requirement_id": parsed.requirement_id,
        "action": parsed.action,
        **result,
    }
    print(json.dumps(payload, sort_keys=True))
    if result["ok"]:
        return 0
    reason = f"{result.get('error_code')}: {result.get('detail') or ''}"
    recovery = str(result.get("recovery") or "Take a screenshot, then retry")
    print(f"{PROG}: {compose_refusal(reason, recovery=recovery)}", file=sys.stderr)
    return 1


def _outcome(parsed: argparse.Namespace, request: dict[str, Any]) -> dict[str, Any] | None:
    """Return the action's result or refusal; None when the lease refused (already printed)."""
    if parsed.text_stdin and parsed.action != "type":
        return _refused(
            "desktop_input_option_unused",
            f"{parsed.action} does not use --text-stdin",
            "Remove --text-stdin; only `type` reads stdin",
        )
    if parsed.action == "type":
        if not parsed.text_stdin:
            return _refused(
                "desktop_input_text_missing",
                "type reads its text from stdin only",
                "Pipe the text and pass --text-stdin, so it never enters argv or shell history",
            )
        request["text"] = sys.stdin.read().removesuffix("\n").removesuffix("\r")
    try:
        validate_request(request)
    except DesktopInputRefused as exc:
        return _refused(exc.code, exc.detail, exc.recovery)
    contract = resolve_mission_contract(parsed, prog=PROG)
    if contract is None:
        return None
    try:
        from yoke_core.domain.machine_qa_host_control import (
            register_test_machine_host_control,
        )

        register_test_machine_host_control()
        return execute_agent_mission_desktop(contract, request)
    except DesktopInputRefused as exc:
        return _refused(exc.code, exc.detail, exc.recovery)
    except HostControlLocalError as exc:
        return _refused(exc.code, str(exc), exc.recovery_hint)
    except Exception as exc:
        return _refused(
            "desktop_input_failed",
            f"local execution failed ({type(exc).__name__})",
            "Check the host with `yoke test-machine verify`, then retry",
        )


def run(args: list[str]) -> int:
    parsed = _parser().parse_args(args)
    request = {
        key: getattr(parsed, key)
        for key in (
            "action", "title", "process", "handle", "name", "automation_id",
            "control_type", "index", "x", "y", "button", "double", "keys", "wait_seconds",
        )
    }
    result = _outcome(parsed, request)
    return 2 if result is None else _finish(parsed, result)


def main(argv: Optional[list[str]] = None) -> int:
    return run(list(sys.argv[1:] if argv is None else argv))


__all__ = ["execute_agent_mission_desktop", "main", "run"]


if __name__ == "__main__":  # pragma: no cover - module adapter
    raise SystemExit(main())
