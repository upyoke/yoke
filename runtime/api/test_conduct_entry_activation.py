"""Regression coverage for conduct's S6f activation block.

S6f used to assume every chain worktree already existed on disk before
the per-task baseline loop ran a `rev-parse`. For multi-worktree epics
that assumption broke: sync recorded N distinct ``epic_dispatch_chains``
rows but the substrate had no creator that materialized them, so conduct
exited with `failure_class=missing_chain_worktrees`.

The unified ``create_worktree`` now provisions every worktree from a
single call. S6f must invoke it *before* the per-task baseline loop so
the downstream subagent dispatch (which targets `${_worktree_path}`
directly under its own `epic_task` work-claim) has the lane to write
into. This module is a doc-shape regression: it would fail against the
pre-fix S6f and pass after the unified-creator call lands.

The baseline itself is read via the main checkout's branch ref
(`git -C "${MAIN_ROOT}" rev-parse "${_worktree_branch}"`) because the
per-task `epic_task` work-claim has not been acquired yet at S6f time —
direct `git -C "${_worktree_path}"` would be blocked by `lint_session_cwd`.
"""

from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
S6F_DOC = (
    REPO_ROOT
    / ".agents"
    / "skills"
    / "yoke"
    / "conduct"
    / "entry-activation-resolution.md"
)


def _doc_text() -> str:
    return S6F_DOC.read_text(encoding="utf-8")


def test_s6f_calls_unified_creator_before_baseline_loop():
    """The unified creator call must precede the per-task baseline loop.

    The baseline loop records `TASK_BASELINE_${_task_id}` via
    `git -C "${MAIN_ROOT}" rev-parse "${_worktree_branch}"` (reading the
    branch ref from the main checkout because the per-task `epic_task`
    work-claim has not been acquired yet — see the hotfix for the
    pre-claim lane-worktree access block). The creator call must still
    run before the loop because the subagent dispatch downstream uses
    `${_worktree_path}` directly. The doc must invoke
    `python3 -m yoke_core.domain.worktree create "${_epic_id}"` above
    that loop.
    """
    text = _doc_text()
    creator_marker = (
        'python3 -m yoke_core.domain.worktree create "${_epic_id}" '
        '--project "${PROJECT}"'
    )
    baseline_marker = (
        'git -C "${MAIN_ROOT}" rev-parse "${_worktree_branch}"'
    )

    assert creator_marker in text, (
        "S6f doc missing unified creator call before the baseline loop"
    )
    assert baseline_marker in text, (
        "S6f baseline marker `git -C ...rev-parse HEAD` not found — "
        "doc shape changed; update this test alongside."
    )

    creator_pos = text.find(creator_marker)
    baseline_pos = text.find(baseline_marker)
    assert creator_pos < baseline_pos, (
        f"S6f doc places the unified creator call (pos={creator_pos}) AFTER "
        f"the per-task baseline loop (pos={baseline_pos}). The creator must "
        f"run first so the baseline `git rev-parse HEAD` succeeds for every "
        f"task in `_task_ids`."
    )


def test_s6f_activates_path_claims_before_unified_creator():
    """Conduct must mirror issue worktree entry's claim-state choreography."""
    text = _doc_text()
    activation_marker = (
        'yoke claims path activation-run --item "${_epic_id}"'
    )
    creator_marker = (
        'python3 -m yoke_core.domain.worktree create "${_epic_id}" '
        '--project "${PROJECT}"'
    )
    lifecycle_disclaimer = (
        "These are path-claim states, not item lifecycle statuses."
    )

    assert activation_marker in text, (
        "S6f doc must activate planned path claims before the creator door-lock"
    )
    assert lifecycle_disclaimer in text, (
        "S6f doc must distinguish path-claim states from item statuses"
    )
    assert text.find(activation_marker) < text.find(creator_marker), (
        "path-claim activation must run before unified worktree creation"
    )


def test_s6f_documents_idempotent_creator_behavior():
    """S6f doc must clarify the creator is idempotent.

    A reader investigating a re-entry path needs to know that lanes already
    on the correct branch are skipped, not recreated. The doc explicitly
    names this contract so future engineers do not work around the call
    fearing accidental rewrites.
    """
    text = _doc_text()
    assert "idempotent" in text.lower(), (
        "S6f doc must mention idempotency so re-entry behavior is explicit"
    )


def test_s6f_creator_passes_project_for_cross_project_epics():
    """S6f doc must pass the inherited PROJECT to the creator.

    Without ``--project "${PROJECT}"`` the unified creator falls back to
    ``_resolve_repo_root_from_cwd``, which for a Yoke-initiated conduct
    session always resolves to the Yoke repo even when the epic targets a
    different project. That is the duplicated cross-project worktree defect
    the advance orchestrator's project routing also fixed.
    """
    text = _doc_text()
    assert '--project "${PROJECT}"' in text, (
        "S6f doc must pass --project so cross-project epic worktrees land "
        "under the target project's checkout, not Yoke's checkout."
    )
    creator_call = (
        'python3 -m yoke_core.domain.worktree create "${_epic_id}" '
        '--project "${PROJECT}"'
    )
    assert creator_call in text, (
        "S6f doc must use the canonical creator invocation shape "
        "with --project on the same line."
    )
