"""Authority for workflow-selected item intake."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Optional, Tuple

from yoke_cli.commands._helpers import usage_error
from yoke_contracts.api.function_call import TargetRef

IDEA_SESSION_MODE = "idea"
ITEMS_CREATE_SKILL_SCAFFOLDING_REFUSAL = "ITEM_SCAFFOLDING_REQUIRED"


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


def refuse_unscaffolded_create(
    *, dry_run: bool, workflow: str, entry_surface: str | None = None
) -> Optional[int]:
    if workflow in ("task", "dash") and entry_surface in (None, "cli", "harness_skill"):
        return None
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
    context = (
        f"workflow={workflow!r}, caller=session mode {mode!r}, "
        f"entry_surface={entry_surface!r}. "
    )
    if workflow in ("task", "dash"):
        recovery = (
            "Use the registered web form or promotion operation for that surface; "
            "direct CLI/skill filing accepts cli/harness_skill. "
            "The workflow still checks its allowed entry surfaces."
        )
    else:
        recovery = (
            "Use /yoke idea to scaffold planned work; it sets session mode idea "
            "and files with entry_surface=harness_skill. "
            "To change an existing item's workflow: re-file with "
            "`/yoke idea --workflow issue|epic|blitz|task` (or "
            "`yoke items create --workflow dash`), cancel the old item with "
            "`yoke items cancel OLD --reason R --ref NEW`, and re-declare any "
            "db claim with `yoke db-claim amend NEW --reason R --payload-file F`."
        )
    return usage_error(f"{ITEMS_CREATE_SKILL_SCAFFOLDING_REFUSAL}: {context}{recovery}")


TASK_VERIFICATION_REFUSAL = (
    "TASK_VERIFICATION_POSTURE_UNSUPPORTED: task v1 has no verification "
    "posture or review stage. File work needing a selected verification plan "
    "or method with yoke dash --title TEXT --spec-file PATH."
)
TASK_PATH_CLAIMS_REFUSAL = (
    "TASK_PATH_CLAIMS_POSTURE_UNSUPPORTED: task v1 does not allow a path-claims "
    "posture. File repository work needing reserved paths with yoke dash "
    "--title TEXT --spec-file PATH."
)
TASK_APPROVAL_REFUSAL = (
    "TASK_APPROVAL_POSTURE_UNSUPPORTED: approval-gated postures are Dash-only "
    "today; task v1 declares approvals=none and no item posture allowlist. "
    "File approval-gated work with yoke dash --title TEXT --spec-file PATH. Task approval "
    "gates await the approvals, notifications, and inbox design."
)
TASK_DEPLOYMENT_REFUSAL = (
    "TASK_DEPLOYMENT_POSTURE_UNSUPPORTED: task v1 is merge-free and has no "
    "deploy-after-merge posture. File work needing item-bound delivery with "
    "yoke dash --title TEXT --spec-file PATH."
)


def _unsupported_posture(parsed: argparse.Namespace) -> Optional[str]:
    if parsed.verification_plan is not None or parsed.verification_method:
        return TASK_VERIFICATION_REFUSAL
    if parsed.path_claims:
        return TASK_PATH_CLAIMS_REFUSAL
    if parsed.approval_on_done:
        return TASK_APPROVAL_REFUSAL
    if parsed.deployment:
        return TASK_DEPLOYMENT_REFUSAL
    return None
