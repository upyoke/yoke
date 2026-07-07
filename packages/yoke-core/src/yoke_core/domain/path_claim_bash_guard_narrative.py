"""Narrative text builders for the path-claim Bash guard.

Extracted from :mod:`path_claim_bash_guard` to keep the guard module
under the 350-line cap. All builders are pure: input dataclasses →
output strings. No DB, no side effects, no ``BashGuardVerdict``
construction (the guard owns that to avoid a circular import).

Three render paths:

* :func:`format_narrative` — concrete failure (out-of-claim or wrong-cwd)
  with a resolved target path. When the target sits under the active
  claim's bound worktree, the narrative pivots to ``worktree_preflight``
  guidance instead of the claim-widening template, since the canonical
  primitive for current-item worktree access is the shared preflight
  surface ( Operator Handoff Addendum).
* :func:`ambiguous_narrative` — opaque shell shape (eval, bash -c,
  heredoc, broken quote) where no target path resolved.
* :func:`worktree_preflight_template` — the literal CLI line operators
  copy when the bash guard points them at the worktree re-entry primitive.
"""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.path_claim_bash_parser import (
    Mutation,
    SUPPRESSION_TOKEN,
)
from yoke_core.domain.path_claim_target_resolver import (
    ClaimContext,
    Failure,
    WORKTREE_UNRESOLVED,
    WRONG_CWD,
    widen_template,
)


def worktree_preflight_template(item_id: int) -> str:
    """Return the canonical worktree_preflight CLI line for an item."""
    return (
        "  python3 -m yoke_core.domain.worktree_preflight "
        f"--item YOK-{int(item_id)}"
    )


def target_under_active_worktree(
    target_path: str,
    ctx: ClaimContext,
    *,
    effective_worktree_path: str = "",
) -> bool:
    """True when ``target_path`` resolves under the bound worktree.

    Used to pivot the deny narrative from "widen the claim" toward
    "use worktree_preflight" when the operator is reaching into the
    current item's own worktree from main scope (the case).
    ``effective_worktree_path`` overrides ``ctx.worktree_path`` when
    set — used for epic items where the bound worktree depends on the
    inbound target. Returns False when no worktree binding
    is available or the target lies elsewhere on disk.
    """
    wt_root = effective_worktree_path or ctx.worktree_path
    if not target_path or not wt_root or not ctx.item_id:
        return False
    try:
        target = Path(target_path).resolve()
        wt = Path(wt_root).resolve()
    except OSError:
        return False
    return target == wt or wt in target.parents


def format_narrative(
    *, mut: Mutation, failure: Failure, ctx: ClaimContext,
) -> str:
    """Render the deny narrative for a concrete-target failure."""
    if failure.mode == WORKTREE_UNRESOLVED:
        return worktree_unresolved_narrative(
            tool_kind=mut.verb, target_path=mut.target_path, ctx=ctx,
        )
    if failure.mode == WRONG_CWD:
        return _wrong_cwd_narrative(mut=mut, failure=failure, ctx=ctx)
    if target_under_active_worktree(
        mut.target_path,
        ctx,
        effective_worktree_path=failure.effective_worktree_path,
    ):
        return _current_item_worktree_narrative(
            mut=mut, ctx=ctx, failure=failure
        )
    return _out_of_claim_narrative(mut=mut, ctx=ctx)


def worktree_unresolved_narrative(
    *, tool_kind: str, target_path: str, ctx: ClaimContext,
) -> str:
    """Render the WORKTREE_UNRESOLVED deny body (shared by Bash+Edit guards).

    The claim has no worktree binding (``items.worktree`` is empty), so
    widening the claim's coverage does not help — the next correct move
    is to provision the worktree via the canonical preflight primitive.
    The claim-widen template is intentionally absent from this
    body so operators do not chase the wrong remediation.
    """
    item_id = int(ctx.item_id or 0)
    preflight = (
        f"  python3 -m yoke_core.domain.worktree_preflight "
        f"--item YOK-{item_id}"
    )
    fallback = (
        f"  python3 -m yoke_core.cli.db_router items update "
        f"{item_id} worktree <branch>"
    )
    return (
        f"BLOCKED: path-claim guard ({tool_kind}).\n"
        f"  target_path:    {target_path}\n"
        f"  claim_id:       {ctx.claim_id}\n"
        f"  failure_mode:   worktree-unresolved\n\n"
        "The active claim is not bound to a worktree (items.worktree is "
        "empty). Provision the worktree via the canonical preflight "
        "primitive — it sets items.worktree and activates the bound "
        "claim:\n\n"
        f"{preflight}\n\n"
        "Or set items.worktree directly when you already have a branch:\n"
        f"{fallback}"
    )


def ambiguous_narrative(*, mut: Mutation, ctx: ClaimContext) -> str:
    """Render the deny narrative for an opaque/ambiguous shell shape."""
    template = widen_template(
        claim_id=ctx.claim_id, item_id=ctx.item_id, target_path="<path>",
    )
    return (
        "BLOCKED: path-claim Bash guard (ambiguous).\n"
        f"  segment:        {mut.target_path}\n"
        f"  failure_mode:   ambiguous\n\n"
        "Compound / `eval` / `bash -c` / here-doc commands cannot be "
        "parsed safely. Rewrite without the compound form, or add the "
        f"suppression token `{SUPPRESSION_TOKEN}` to the command body "
        "(audit evidence will be recorded).\n\n"
        "If the command targets one path, widen the claim instead:\n"
        f"  {template}"
    )


def _wrong_cwd_narrative(
    *, mut: Mutation, failure: Failure, ctx: ClaimContext,
) -> str:
    template = widen_template(
        claim_id=ctx.claim_id, item_id=ctx.item_id,
        target_path=mut.target_path,
    )
    expected_wt = failure.effective_worktree_path or ctx.worktree_path
    return (
        f"BLOCKED: path-claim Bash guard ({mut.verb}).\n"
        f"  target_path:        {mut.target_path}\n"
        f"  resolved_parent:    {failure.resolved_parent}\n"
        f"  expected_worktree:  {expected_wt}\n"
        f"  failure_mode:       wrong-cwd\n\n"
        "Wrong working tree — expected "
        f"`{expected_wt}`, got `{failure.resolved_parent}`. "
        "Relaunch Claude Code rooted at the worktree.\n\n"
        "Or widen the claim to cover this physical path:\n"
        f"  {template}"
    )


def _current_item_worktree_narrative(
    *, mut: Mutation, ctx: ClaimContext, failure: Failure,
) -> str:
    """Pivot the OOC narrative when the target is under the bound worktree.

    The operator is reaching into the current item's own worktree from
    main. The canonical primitive is ``worktree_preflight`` — it
    acquires the work-claim and provisions the worktree. Once the
    session holds the claim, ``lint_session_cwd`` authorizes writes
    under the worktree via the claim, regardless of harness cwd. Claim
    widening (for a specific path the current claim doesn't cover)
    remains an option but is no longer the headline.
    """
    template = widen_template(
        claim_id=ctx.claim_id, item_id=ctx.item_id,
        target_path=mut.target_path,
    )
    preflight = worktree_preflight_template(int(ctx.item_id or 0))
    expected_wt = failure.effective_worktree_path or ctx.worktree_path
    return (
        f"BLOCKED: path-claim Bash guard ({mut.verb}).\n"
        f"  target_path:    {mut.target_path}\n"
        f"  claim_id:       {ctx.claim_id}\n"
        f"  expected_worktree: {expected_wt}\n"
        f"  failure_mode:   out-of-claim (current-item worktree)\n\n"
        "The target is inside the current item's bound worktree but "
        "outside the active claim's coverage. Use the canonical "
        "worktree re-entry primitive — it acquires the work-claim and "
        "provisions the worktree (lint_session_cwd then authorizes "
        "writes under the worktree per call):\n\n"
        f"{preflight}\n\n"
        "If the operation needs a path the claim does not cover, widen "
        "the claim instead:\n"
        f"  {template}\n\n"
        f"Or add `{SUPPRESSION_TOKEN}` to bypass with audit evidence."
    )


def _out_of_claim_narrative(*, mut: Mutation, ctx: ClaimContext) -> str:
    template = widen_template(
        claim_id=ctx.claim_id, item_id=ctx.item_id,
        target_path=mut.target_path,
    )
    covered_preview = ", ".join(ctx.covered_paths[:3]) or "(no coverage)"
    extra_count = max(0, len(ctx.covered_paths) - 3)
    extra_str = f" (+{extra_count} more)" if extra_count else ""
    return (
        f"BLOCKED: path-claim Bash guard ({mut.verb}).\n"
        f"  target_path:    {mut.target_path}\n"
        f"  claim_id:       {ctx.claim_id}\n"
        f"  covered:        {covered_preview}{extra_str}\n"
        f"  failure_mode:   out-of-claim\n\n"
        "Path is outside this session's active claim coverage.\n"
        "Widen the claim's coverage:\n"
        f"  {template}\n\n"
        f"Or add `{SUPPRESSION_TOKEN}` to bypass with audit evidence."
    )


__all__ = [
    "ambiguous_narrative",
    "format_narrative",
    "target_under_active_worktree",
    "worktree_preflight_template",
    "worktree_unresolved_narrative",
]
