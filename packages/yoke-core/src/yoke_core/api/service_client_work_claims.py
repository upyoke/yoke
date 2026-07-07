"""Typed work-claim service-client surface — ``claim-work`` / ``release-work-claim``.

Every claim mutation flows through this module so callers cannot smuggle a
malformed target shape past the CHECK constraint. Subcommand grammar and
canonical reason vocabularies are taught in ``--help`` (see
``service_client_work_claim_acquire_reason_help`` / ``..._reason_help``).
``--session-id`` is optional; when supplied it must equal the caller's
ambient session — see ``service_client_work_claims_identity``.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Optional

from yoke_core.domain.work_claim_targets import (
    TARGET_KIND_EPIC_TASK,
    TARGET_KIND_ITEM,
    TARGET_KIND_PROCESS,
    TargetValidationError,
    WorkClaimTarget,
    make_epic_task_target,
    make_item_target,
    make_process_target,
)
from yoke_core.domain.work_processes import (
    UnknownProcessError,
    is_known_process,
)
from yoke_core.api.service_client_shared import (
    _get_db_readonly,
    _get_db_readwrite,
    normalize_claim_item_id,
)
from yoke_core.api.service_client_sessions_lifecycle_touch import (
    _validate_active_session,
)
from yoke_core.api.service_client_work_claim_acquire_reason_help import (
    CLAIM_WORK_DESCRIPTION,
    render_acquire_reason_help_text,
)
from yoke_core.api.service_client_work_claim_reason_help import render_reason_help_text
from yoke_core.api.service_client_work_claims_identity import (
    check_self_only_session_identity,
)

DEFAULT_PROCESS_PROJECT = "yoke"

CLAIM_EXIT_OK = 0
CLAIM_EXIT_USAGE = 2
CLAIM_EXIT_FAIL = 1

RELEASE_EXIT_OK = 0
RELEASE_EXIT_USAGE = 2
RELEASE_EXIT_NOT_OWNED = 3
RELEASE_EXIT_ALREADY_TERMINAL = 4
RELEASE_EXIT_ITEM_NOT_FOUND = 5
RELEASE_EXIT_DOMAIN_ERROR = 6
RELEASE_EXIT_PRECONDITION_REFUSED = 7

_RELEASE_FAILURE_TO_EXIT = {
    "not_owned": RELEASE_EXIT_NOT_OWNED,
    "already_terminal": RELEASE_EXIT_ALREADY_TERMINAL,
    "item_not_found": RELEASE_EXIT_ITEM_NOT_FOUND,
    "domain_error": RELEASE_EXIT_DOMAIN_ERROR,
    "non_terminal_release_refused": RELEASE_EXIT_PRECONDITION_REFUSED,
}


def _require_self_session(explicit: Optional[str]) -> Optional[str]:
    identity = check_self_only_session_identity(explicit)
    if identity.ok:
        return identity.effective_session_id
    print(json.dumps({"success": False, "code": identity.code,
                      "error": identity.message}), file=sys.stderr)
    return None


def _parse_target_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--item", default=None,
                        help="Item target (YOK-N or bare numeric)")
    parser.add_argument("--epic-task", default=None, dest="epic_task",
                        help="Epic-task target epic id (YOK-EPIC); pair with --task-num")
    parser.add_argument("--task-num", default=None, type=int, dest="task_num")
    parser.add_argument("--process", default=None,
                        help="Recurring process key (e.g. STRATEGIZE, FEED, DOCTOR)")
    parser.add_argument("--project", default=DEFAULT_PROCESS_PROJECT,
                        help="Project scope for process target conflict groups")


def _resolve_target(parsed: argparse.Namespace) -> WorkClaimTarget:
    """Convert parsed flags into exactly one validated WorkClaimTarget.

    Refuses ambiguous or empty target specs at the CLI boundary so the
    domain layer never sees a malformed payload.
    """
    declared = [
        ("item", parsed.item),
        ("epic-task", parsed.epic_task),
        ("process", parsed.process),
    ]
    populated = [name for name, val in declared if val]
    if not populated:
        raise TargetValidationError(
            "must declare exactly one target: --item, --epic-task, or --process"
        )
    if len(populated) > 1:
        raise TargetValidationError(
            f"cannot declare multiple targets in one call: {populated}"
        )
    if parsed.item:
        return make_item_target(int(normalize_claim_item_id(parsed.item)))
    if parsed.epic_task:
        if parsed.task_num is None:
            raise TargetValidationError(
                "--epic-task requires --task-num"
            )
        return make_epic_task_target(
            int(normalize_claim_item_id(parsed.epic_task)),
            parsed.task_num,
        )
    # process
    if not is_known_process(parsed.process):
        raise UnknownProcessError(
            f"unknown process key {parsed.process!r}"
        )
    return make_process_target(parsed.process, parsed.project)


def cmd_claim_work(args: list[str]) -> int:
    """Acquire a typed work claim for the active session."""
    parser = argparse.ArgumentParser(
        prog="claim-work", add_help=True,
        description=CLAIM_WORK_DESCRIPTION,
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--session-id", default=None)
    parser.add_argument(
        "--reason", "--intent", dest="reason", default=None,
        help=render_acquire_reason_help_text(),
    )
    _parse_target_flags(parser)

    try:
        parsed = parser.parse_args(args)
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        print(
            "Usage: claim-work [--session-id S] [--reason R] (--item YOK-N | "
            "--epic-task YOK-EPIC --task-num K | --process KEY [--project P])",
            file=sys.stderr,
        )
        return CLAIM_EXIT_USAGE

    parsed.session_id = _require_self_session(parsed.session_id)
    if parsed.session_id is None:
        return CLAIM_EXIT_USAGE

    try:
        target = _resolve_target(parsed)
    except (TargetValidationError, UnknownProcessError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}), file=sys.stderr)
        return CLAIM_EXIT_USAGE

    conn = _get_db_readonly()
    try:
        if not _validate_active_session(conn, parsed.session_id):
            return CLAIM_EXIT_FAIL
    finally:
        conn.close()

    result = _claim_work_direct(
        parsed.session_id, target, reason=parsed.reason,
    )

    if result["success"]:
        print(json.dumps({"success": True, "claim": result["claim"]}))
        return CLAIM_EXIT_OK
    print(
        json.dumps({
            "success": False,
            "code": result.get("code"),
            "error": result["error"],
        }),
        file=sys.stderr,
    )
    return CLAIM_EXIT_FAIL


def _claim_work_direct(
    session_id: str,
    target: WorkClaimTarget,
    *,
    reason: Optional[str] = None,
) -> dict[str, object]:
    from yoke_core.domain.sessions import SessionError, claim_work

    conn = _get_db_readwrite()
    try:
        try:
            claim = claim_work(
                conn, session_id=session_id, target=target, reason=reason,
            )
        except SessionError as exc:
            message = exc.message
            if exc.code == "ALREADY_CLAIMED" and "already claimed" not in message:
                message = f"work target already claimed: {message}"
            return {"success": False, "code": exc.code, "error": message}
        except Exception as exc:  # noqa: BLE001 - CLI boundary preserves JSON error.
            return {"success": False, "code": "claim_failed", "error": str(exc)}
        return {"success": True, "claim": claim}
    finally:
        conn.close()


def cmd_release_work_claim(args: list[str]) -> int:
    """Release an execution-owned typed work claim."""
    from yoke_core.domain.sessions import release_work_claim_for_execution
    from yoke_core.domain.sessions_lifecycle_release_precondition import (
        emit_release_override,
    )

    parser = argparse.ArgumentParser(
        prog="release-work-claim", add_help=True,
        description="Release an execution-owned typed work claim.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument("--session-id", default=None)
    parser.add_argument(
        "--reason", "--intent", dest="reason", required=True,
        help=render_reason_help_text(),
    )
    parser.add_argument(
        "--allow-non-terminal", action="store_true", default=False,
        dest="allow_non_terminal",
        help="Operator bypass: non-terminal release without terminal "
             "evidence. Requires --override-rationale.",
    )
    parser.add_argument(
        "--override-rationale", default=None, dest="override_rationale",
        help="Operator rationale recorded with --allow-non-terminal.",
    )
    _parse_target_flags(parser)

    try:
        parsed = parser.parse_args(args)
    except SystemExit as exc:
        if exc.code == 0:
            return 0
        return RELEASE_EXIT_USAGE

    parsed.session_id = _require_self_session(parsed.session_id)
    if parsed.session_id is None:
        return RELEASE_EXIT_USAGE

    if parsed.allow_non_terminal and not parsed.override_rationale:
        print(
            "Error: --allow-non-terminal requires --override-rationale STR",
            file=sys.stderr,
        )
        return RELEASE_EXIT_USAGE
    if parsed.override_rationale and not parsed.allow_non_terminal:
        print(
            "Error: --override-rationale requires --allow-non-terminal",
            file=sys.stderr,
        )
        return RELEASE_EXIT_USAGE

    try:
        target = _resolve_target(parsed)
    except (TargetValidationError, UnknownProcessError) as exc:
        print(json.dumps({"success": False, "error": str(exc)}), file=sys.stderr)
        return RELEASE_EXIT_USAGE

    conn = _get_db_readwrite()
    try:
        try:
            result = release_work_claim_for_execution(
                conn, parsed.session_id, target, parsed.reason,
                allow_non_terminal=parsed.allow_non_terminal,
            )
            if parsed.allow_non_terminal and result.get("released") and result.get("claim_id"):
                emit_release_override(
                    session_id=parsed.session_id, target=target,
                    claim_id=int(result["claim_id"]),
                    reason=parsed.reason,
                    operator_rationale=parsed.override_rationale or "",
                )
        except ValueError as exc:
            target_label = target.render()
            print(
                f"Warning: claim release failed for {target_label} "
                f"(reason=domain_error): {exc}",
                file=sys.stderr,
            )
            print(json.dumps({
                "success": False,
                "released": False,
                "failure_reason": "domain_error",
                "error": str(exc),
            }))
            return RELEASE_EXIT_DOMAIN_ERROR
    finally:
        conn.close()

    if result.get("released"):
        print(json.dumps({"success": True, **result}))
        return RELEASE_EXIT_OK

    failure_reason = result.get("failure_reason", "unknown")
    holder = result.get("holder_session_id")
    holder_clause = f" held by session '{holder}'" if holder else ""
    target_label = target.render()
    print(
        f"Warning: claim release failed for {target_label} "
        f"(reason={failure_reason}){holder_clause}: see events for "
        f"ItemClaimReleaseFailed.",
        file=sys.stderr,
    )
    print(json.dumps({"success": False, **result}))
    return _RELEASE_FAILURE_TO_EXIT.get(failure_reason, RELEASE_EXIT_DOMAIN_ERROR)


WORK_CLAIM_COMMANDS = {
    "claim-work": cmd_claim_work,
    "release-work-claim": cmd_release_work_claim,
}


__all__ = [
    "DEFAULT_PROCESS_PROJECT",
    "WORK_CLAIM_COMMANDS",
    "cmd_claim_work",
    "cmd_release_work_claim",
]
