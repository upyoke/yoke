"""``yoke items create`` workflow-selected creation adapter.

Wraps the ``items.create`` function id. Callers name the workflow and the
typed entry surface through which they are creating it.

Same envelope over both transports: a local universe dispatches
in-process, and an https connection POSTs the same
``FunctionCallRequest`` to ``/v1/functions/call`` — which is what makes
``/yoke idea`` work against a prod-https control plane.

The adapter itself is the scaffolding gate: a live harness session that
is not in idea mode is refused, because ``--entry-surface`` is
caller-asserted and does not perform skill-side dedup, classification,
or body work. Retained callers are operator/debug (no ambient session),
``--dry-run``, test isolation, and ``/yoke idea`` (session mode
``idea``). Everyone else files through ``/yoke idea`` or
``yoke dash TITLE INSTRUCTION`` or ``yoke task TITLE INSTRUCTION``.
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.api.function_call import TargetRef


__all__ = [
    "IDEA_SESSION_MODE",
    "ITEMS_CREATE_SKILL_SCAFFOLDING_REFUSAL",
    "ITEMS_CREATE_USAGE",
    "allow_low_level_items_create",
    "items_create",
]


IDEA_SESSION_MODE = "idea"

ITEMS_CREATE_SKILL_SCAFFOLDING_REFUSAL = (
    "yoke items create is operator/debug, dry-run, and test-isolation only. "
    "A live harness session files through skill-side scaffolding: "
    "/yoke idea for issue, epic, or blitz; "
    "yoke dash TITLE INSTRUCTION for dash; "
    "yoke task TITLE INSTRUCTION for laneless, merge-free task."
)

ITEMS_CREATE_USAGE = (
    "yoke items create TITLE [WORKFLOW] --execution-instructions-considered "
    "[--priority P] [--project NAME] "
    "[--deployment-flow FLOW] [--status STATUS] [--source ACTOR] "
    "[--owner ACTOR] [--entry-surface SURFACE] [--strategy-doc SLUG] "
    "[--dry-run] [--session-id S] [--json]"
)


def allow_low_level_items_create(
    *,
    dry_run: bool,
    test_isolated: bool,
    ambient_session_id: Optional[str],
    session_mode: Optional[str],
) -> bool:
    """Return whether this adapter may dispatch ``items.create``.

    Gate on the caller class, not on the unverified ``--entry-surface``
    token. ``/yoke idea`` keeps this adapter as its create surface and
    authorizes that use by stamping session mode ``idea`` first.
    """
    if dry_run or test_isolated:
        return True
    if not ambient_session_id:
        return True
    return session_mode == IDEA_SESSION_MODE


def _is_test_isolation() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) or "pytest" in sys.modules


def _ambient_session_id() -> Optional[str]:
    from yoke_cli.transport.dispatcher import _resolve_session_id

    return _resolve_session_id()


def _session_mode(session_id: str) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(mode, error_message)`` from the stored session row."""
    from yoke_cli.transport.dispatcher import build_actor, call_dispatcher

    response = call_dispatcher(
        function_id="sessions.identity",
        target=TargetRef(kind="global"),
        payload={},
        actor=build_actor(session_id=session_id),
    )
    if not response.success:
        detail = (
            response.error.message
            if response.error is not None
            else "sessions.identity failed"
        )
        return None, (f"{detail} Recover with: yoke sessions identity")
    mode = response.result.get("mode")
    return (str(mode) if mode else None), None


def _refuse_unscaffolded_create(*, dry_run: bool) -> Optional[int]:
    test_isolated = _is_test_isolation()
    ambient = None if (dry_run or test_isolated) else _ambient_session_id()
    mode: Optional[str] = None
    if ambient:
        mode, identity_error = _session_mode(ambient)
        if identity_error:
            return usage_error(identity_error)
    if allow_low_level_items_create(
        dry_run=dry_run,
        test_isolated=test_isolated,
        ambient_session_id=ambient,
        session_mode=mode,
    ):
        return None
    return usage_error(ITEMS_CREATE_SKILL_SCAFFOLDING_REFUSAL)


def items_create(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke items create",
        description=ITEMS_CREATE_USAGE,
    )
    parser.add_argument("title", help="Item title (<=100 chars).")
    parser.add_argument(
        "workflow",
        nargs="?",
        default=None,
        help="Workflow id; temporarily defaults to issue.",
    )
    parser.add_argument(
        "--priority",
        default=None,
        help="Priority bucket; defaults to the project default.",
    )
    parser.add_argument(
        "--project",
        default=None,
        help="Project slug/id (default: the checkout's mapped project).",
    )
    parser.add_argument(
        "--deployment-flow",
        dest="deployment_flow",
        default=None,
        help="Deployment flow id.",
    )
    parser.add_argument(
        "--status",
        default=None,
        help="Initial stage; defaults to the workflow's first stage.",
    )
    parser.add_argument(
        "--source",
        default=None,
        help="Numeric source actor id (default: authenticated/session actor).",
    )
    parser.add_argument(
        "--owner", default=None, help="Numeric owner actor id (default: source actor)."
    )
    parser.add_argument(
        "--entry-surface",
        choices=("cli", "harness_skill", "promotion", "web_form"),
        default=None,
        help="Typed creation surface allowed by the workflow.",
    )
    parser.add_argument(
        "--strategy-doc",
        metavar="SLUG",
        default=None,
        help=(
            "Strategy document this item belongs to; makes it a member of "
            "that document's steering scope from the moment it is filed."
        ),
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        help="Preview only; no row created, no GitHub sync.",
    )
    parser.add_argument(
        "--execution-instructions-considered",
        dest="execution_instructions_considered",
        action="store_true",
        help=(
            "Attest that this filer retrieved the operator execution "
            "instructions for this workflow and project first (yoke "
            "workflow execution-instruction resolve). Required for "
            "this surface."
        ),
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, ITEMS_CREATE_USAGE)
    if parsed is None:
        return 2
    refused = _refuse_unscaffolded_create(dry_run=bool(parsed.dry_run))
    if refused is not None:
        return refused

    payload: Dict[str, Any] = {
        "title": parsed.title,
        "dry_run": bool(parsed.dry_run),
        # Passed through, never inferred: the flag attests what the filer
        # did before authoring, which this adapter cannot observe.
        "execution_instructions_considered": bool(
            parsed.execution_instructions_considered
        ),
    }
    if parsed.workflow is not None:
        payload["workflow"] = parsed.workflow
    if parsed.status is not None:
        payload["status"] = parsed.status
    if parsed.priority is not None:
        payload["priority"] = parsed.priority
    project = client_project_context(parsed.project)
    if project is not None:
        payload["project"] = project
    if parsed.deployment_flow is not None:
        payload["deployment_flow"] = parsed.deployment_flow
    if parsed.source is not None:
        payload["source"] = parsed.source
    if parsed.owner is not None:
        payload["owner"] = parsed.owner
    if parsed.entry_surface is not None:
        payload["entry_surface"] = parsed.entry_surface
    if parsed.strategy_doc is not None:
        payload["strategy_doc"] = parsed.strategy_doc

    return dispatch_and_emit(
        function_id="items.create",
        target=TargetRef(kind="global", project_id=project),
        payload=payload,
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
