"""Resolve the registered verification obligation for a merge candidate."""

from __future__ import annotations

from typing import Tuple

from yoke_core.domain.public_item_target import public_item_target
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain import control_plane_function_degradation

NO_TESTS_ATTESTED = "no_tests_attested"

POST_REBASE_TRANSITION_ID = "release"
# Older control-plane builds validate the transition against the pinned
# workflow first, so workflows without `release` try these real stages next.
_POST_REBASE_TRANSITION_FALLBACKS = (
    "reviewing-implementation",
    "done",
)


def _resolve_requirement(item_id: int, transition_id: str, materialize: bool = True):
    """Ask for the post-rebase verification command, degrading on skew.

    A wave whose own branch adds this function leaves the deployed plane
    behind the client that is merging it, so the resolver continues through
    the paired direct-Postgres connection instead of demanding the release
    that cannot happen until this merge lands.
    """
    return control_plane_function_degradation.dispatch_through_paired_admin_on_skew(
        function_id="merge.tests.post_rebase_requirement",
        target=public_item_target(item_id),
        payload={"transition_id": transition_id, "materialize": materialize},
        announce=print,
        # This module's own binding, resolved per call, so the transport
        # seam every merge test substitutes stays the single one.
        dispatch=call_dispatcher,
    )


def _post_rebase_transition_candidates(item_id: int) -> list[str]:
    """Ordered transition ids to try for post-rebase plan materialization."""
    ordered = [POST_REBASE_TRANSITION_ID, *_POST_REBASE_TRANSITION_FALLBACKS]
    try:
        resp = call_dispatcher(
            function_id="items.detail.get",
            target=public_item_target(item_id),
            payload={},
        )
    except Exception:  # noqa: BLE001 - detail lookup is advisory for ordering
        return ordered
    if not resp.success or not resp.result:
        return ordered
    status = str((resp.result.get("item") or {}).get("status") or "").strip()
    if status and status in ordered:
        return [status, *[c for c in ordered if c != status]]
    return ordered


def _is_unknown_workflow_transition(message: str) -> bool:
    return "is not in" in message and "workflow transition" in message


def resolve_verification(
    item_id: str, *, materialize: bool = True
) -> Tuple[str, str, list]:
    """``(scope, command, covering_runs)``, or ``(NO_TESTS_ATTESTED, reason, [])``.

    A refusal raises ``RuntimeError`` with the server's reason and recovery;
    ``materialize=False`` is the read-only form ``merge item --check`` asks.
    """
    last_code = "unknown"
    last_message = ""
    last_recovery = ""
    for transition_id in _post_rebase_transition_candidates(item_id):
        try:
            resp = _resolve_requirement(item_id, transition_id, materialize)
        except Exception as exc:  # noqa: BLE001 - resolver failure blocks merge.
            raise RuntimeError(
                f"integration verification dispatcher failed: {exc}"
            ) from exc
        if resp.success:
            result = resp.result or {}
            if result.get("no_tests_reason"):
                return NO_TESTS_ATTESTED, str(result["no_tests_reason"]), []
            scope = str(result.get("scope") or "").strip()
            command = str(result.get("command") or "").strip()
            if scope not in {"full", "quick"} or not command:
                raise RuntimeError(
                    "integration verification resolver returned no executable "
                    "registered full or quick command"
                )
            covering = result.get("covering_runs")
            return scope, command, covering if isinstance(covering, list) else []
        last_code = (resp.error.code if resp.error else "unknown") or "unknown"
        last_message = (resp.error.message if resp.error else "") or ""
        last_recovery = getattr(resp.error, "recovery_hint", "") or ""
        if not _is_unknown_workflow_transition(last_message):
            break
    # The recovery hint is the actionable half of a skew or authority
    # refusal; dropping it is what turned a fixable condition into an
    # opaque "test command unavailable".
    detail = (
        f"{last_message} {last_recovery}".strip() if last_recovery else last_message
    )
    raise RuntimeError(
        f"integration verification resolution failed ({last_code}): {detail}"
    )


