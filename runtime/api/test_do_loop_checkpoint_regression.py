"""Regression tests for do-loop checkpoints and advance summary handoff wording."""

from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
LOOP_ROUTING = REPO_ROOT / ".agents/skills/yoke/do/loop-routing.md"
FINALIZE = REPO_ROOT / ".agents/skills/yoke/advance/finalize.md"
ADVANCE_SKILL = REPO_ROOT / ".agents/skills/yoke/advance/SKILL.md"


def test_loop_routing_pre_dispatch_checkpoint_before_resume():
    """AC-3/AC-6: pre-dispatch checkpoint appears before the first action-specific dispatch section."""
    text = LOOP_ROUTING.read_text()

    pre_dispatch_idx = text.find("--outcome \"pre-dispatch\"")
    assert pre_dispatch_idx != -1, (
        "loop-routing.md must contain a session-checkpoint call with --outcome \"pre-dispatch\" "
        "before any action-specific handler section"
    )

    first_handler_idx = text.find("#### `resume`")
    assert first_handler_idx != -1, "loop-routing.md must contain a '#### `resume`' section"

    assert pre_dispatch_idx < first_handler_idx, (
        "Pre-dispatch checkpoint (--outcome \"pre-dispatch\") must appear before '#### `resume`' "
        f"in loop-routing.md (found at {pre_dispatch_idx}, resume at {first_handler_idx})"
    )


def test_loop_routing_post_handler_checkpoint_is_outcome_aware():
    """The post-handler checkpoint classifies outcomes before Step C."""
    text = LOOP_ROUTING.read_text()

    assert text.count("--outcome \"pre-dispatch\"") == 1, (
        "loop-routing.md must contain exactly one pre-dispatch checkpoint instruction"
    )
    assert "classify_advance_outcome" in text, (
        "Post-handler checkpoint must classify advance slice vs completed outcomes"
    )
    assert '--outcome "$_handler_outcome"' in text, (
        "Post-handler checkpoint must persist the classified handler outcome"
    )
    assert "CHAIN HANDLER OUTCOME" in text, (
        "Non-completed outcomes must not render as CHAIN STEP COMPLETE"
    )
    assert "render_chain_summary_label" in text, (
        "Loop summary must use the canonical handler-outcome labels"
    )
    assert 'with `--outcome "completed"`' not in text, (
        "Scope-entry wording must not force completed after classification"
    )
    assert "scheduler `next_step`" in text, (
        "Charge dispatch must retain scheduler.next_step for outcome classification"
    )


def test_loop_followups_preserves_interactive_process_claims():
    """Interactive process checkpoints stop without generic cleanup."""
    text = (REPO_ROOT / ".agents/skills/yoke/do/loop-followups.md").read_text()

    assert "If `_cp_outcome` is `interactive_checkpoint`" in text
    assert "stop the loop without Step D" in text
    assert "must not release the intentionally-open process claim" in text


def test_finalize_step_10b_do_loop_context_is_target_aware():
    """The advance summary must distinguish active review work from the real boundary."""
    text = FINALIZE.read_text()

    compact_block_start = text.find("## Compact-Resistant Summary (step 10b)")
    assert compact_block_start != -1, (
        "finalize.md must have a '## Compact-Resistant Summary (step 10b)' section"
    )

    block_text = text[compact_block_start:]

    assert "{step}" in block_text, (
        "finalize.md step 10b must include a {step} placeholder for the do-loop frame"
    )
    assert "{MAX_CHAIN_STEPS}" in block_text, (
        "finalize.md step 10b must include a {MAX_CHAIN_STEPS} placeholder for the do-loop frame"
    )
    assert "{chainable}" in block_text, (
        "finalize.md step 10b must include a {chainable} placeholder for the do-loop frame"
    )

    do_loop_idx = block_text.find("Do-loop context")
    assert do_loop_idx != -1, (
        "finalize.md step 10b must label the compact-resistant summary line as Do-loop context"
    )

    fence_end = block_text.find("\n```", do_loop_idx)
    do_loop_window = (
        block_text[do_loop_idx:fence_end] if fence_end != -1 else block_text[do_loop_idx:]
    )

    stale_unconditional_instruction = (
        "after this advance completes, "
        + "return to /yoke do "
        + "Step C (chain decision)"
    )
    assert stale_unconditional_instruction not in do_loop_window, (
        "finalize.md step 10b must not restore the old unconditional instruction "
        "that every advance completion returns to the do-loop"
    )
    assert "Step B" not in do_loop_window, (
        "finalize.md step 10b must label the loop chain-decision step as "
        "'Step C (chain decision)' so the do-loop step references stay in "
        "sync with do/loop-followups.md (which owns Step C)"
    )

    assert "reviewing-implementation" in do_loop_window, (
        "finalize.md step 10b Do-loop context bullet must explicitly name "
        "reviewing-implementation as a target where the same session continues the "
        "review/fix/verify loop instead of returning to /yoke do"
    )
    assert "reviewed-implementation" in do_loop_window, (
        "finalize.md step 10b Do-loop context bullet must explicitly name "
        "reviewed-implementation as the command boundary target where the advance "
        "contract completes"
    )

    review_bullet_start = do_loop_window.find(
        "When `{_target}` is `implementing` or `reviewing-implementation`"
    )
    boundary_bullet_start = do_loop_window.find(
        "When `{_target}` is `reviewed-implementation`"
    )
    assert review_bullet_start != -1, (
        "finalize.md step 10b must include a target-specific bullet for "
        "implementing/reviewing-implementation"
    )
    assert boundary_bullet_start != -1, (
        "finalize.md step 10b must include a target-specific bullet for "
        "reviewed-implementation"
    )

    review_bullet = do_loop_window[review_bullet_start:boundary_bullet_start]
    boundary_bullet = do_loop_window[boundary_bullet_start:]

    assert "advance contract is NOT complete" in review_bullet
    assert "same session and worktree" in review_bullet
    assert "/yoke advance YOK-{N} reviewed-implementation" in review_bullet
    assert "advance contract IS complete" in boundary_bullet
    assert "Return to /yoke do Step C (chain decision)" in boundary_bullet


def test_advance_handoff_prose_does_not_advertise_polish_command():
    """AC-1/AC-2/AC-3: advance prose at the reviewed-implementation boundary
    must not invite the routed agent to invoke `/yoke polish` directly.
    The boundary message routes back through `/yoke do` (or stops for a
    fresh entrypoint); polish is the routed loop's call to make."""
    finalize_text = FINALIZE.read_text()
    skill_text = ADVANCE_SKILL.read_text()

    # Finalize.md no longer advertises the inline polish command at the boundary
    assert "Or run `/yoke polish" not in finalize_text, (
        "AC-2: advance/finalize.md must not present an inline `/yoke polish` "
        "command at the reviewed-implementation boundary"
    )
    assert "scheduler will route this item to `/yoke polish`" not in finalize_text, (
        "AC-2: advance/finalize.md must not promise the scheduler will route to "
        "`/yoke polish` from inside the advance flow"
    )

    # There is exactly one reviewed-implementation next-step message,
    # and it routes back through /yoke do or a fresh entrypoint.
    boundary_section = "**If target was `reviewed-implementation`"
    boundary_idx = finalize_text.find(boundary_section)
    assert boundary_idx != -1, (
        "advance/finalize.md must contain the reviewed-implementation Pre-Release "
        "Next-Step Guidance bullet"
    )
    # Only one occurrence of this bullet
    assert finalize_text.count(boundary_section) == 1, (
        "AC-1: exactly one reviewed-implementation Pre-Release Next-Step bullet"
    )
    # The bullet routes through /yoke do
    boundary_block_end = finalize_text.find(
        "**If target was", boundary_idx + len(boundary_section)
    )
    if boundary_block_end == -1:
        boundary_block_end = len(finalize_text)
    boundary_block = finalize_text[boundary_idx:boundary_block_end]
    assert "Return to `/yoke do`" in boundary_block, (
        "AC-1: reviewed-implementation boundary must route back through `/yoke do`"
    )
    assert "fresh command entrypoint" in boundary_block, (
        "AC-1: reviewed-implementation boundary must mention the fresh-entrypoint "
        "alternative for direct operator invocation"
    )

    # SKILL.md re-entry bullet for reviewed-implementation no longer says
    # "invoke /yoke polish" — it delegates to the boundary guidance.
    review_reentry = "If target is `reviewed-implementation` → reviewed-implementation re-entry."
    review_reentry_idx = skill_text.find(review_reentry)
    assert review_reentry_idx != -1, (
        "advance/SKILL.md must keep a reviewed-implementation re-entry bullet"
    )
    review_reentry_end = skill_text.find("\n", review_reentry_idx)
    review_reentry_line = skill_text[review_reentry_idx:review_reentry_end]
    assert "invoke `/yoke polish`" not in review_reentry_line, (
        "AC-3: SKILL.md re-entry bullet must not invite `/yoke polish` invocation"
    )
    assert "boundary" in review_reentry_line, (
        "AC-3: SKILL.md re-entry bullet must delegate to the boundary message"
    )


def test_loop_routing_wait_branch_handles_no_lane_compatible_work():
    """AC-9: do-loop WAIT rendering must have a special branch for
    `wait_reason="no_lane_compatible_work"` and must not print the generic
    `No actionable work exists on the frontier` line in that branch."""
    text = LOOP_ROUTING.read_text()

    wait_section_idx = text.find("#### `wait`")
    assert wait_section_idx != -1, "loop-routing.md must contain a #### `wait` section"
    wait_section = text[wait_section_idx:]

    assert '"no_lane_compatible_work"' in wait_section, (
        "AC-9: WAIT branch must explicitly handle wait_reason=\"no_lane_compatible_work\""
    )
    assert "context.actual_lane" in wait_section, (
        "AC-9: WAIT lane-filtered branch must surface context.actual_lane to the operator"
    )
    assert "Paths blocked for this lane" in wait_section, (
        "AC-9: WAIT lane-filtered branch must render the lane_filtered_paths view"
    )
    assert "Truly-empty branch" in wait_section, (
        "AC-9: WAIT must keep a separate truly-empty branch for the generic idle case"
    )

    # The lane-filtered branch must not duplicate the generic idle text — the
    # generic text only appears in the truly-empty branch.
    lane_branch_idx = wait_section.find('"no_lane_compatible_work"')
    truly_empty_idx = wait_section.find("Truly-empty branch")
    lane_branch_window = wait_section[lane_branch_idx:truly_empty_idx]
    assert "No actionable work exists on the frontier" not in lane_branch_window, (
        "AC-9: lane-filtered WAIT branch must not print the generic frontier-empty text"
    )


def test_loop_routing_escalate_branch_no_longer_emits_lane_mismatch():
    """AC-5/AC-7: lane_mismatch is no longer an escalate reason. The escalate
    branch keeps the lane-filtered ride-along rendering for blocker cases but
    drops the standalone lane_mismatch options block."""
    text = LOOP_ROUTING.read_text()

    escalate_idx = text.find("#### `escalate`")
    assert escalate_idx != -1, "loop-routing.md must contain a #### `escalate` section"
    next_section_idx = text.find("#### `feed`", escalate_idx)
    escalate_section = text[escalate_idx:next_section_idx]

    # Lane-filtered count rendering still applies to the escalate ride-along case
    assert "context.lane_filtered_count > 0" in escalate_section, (
        "AC-7: escalate must still render lane_filtered detail when both apply"
    )
    # The standalone lane mismatch path is gone from escalate — it is now WAIT.
    assert '"lane_mismatch"' not in escalate_section, (
        "AC-5/AC-7: escalate must no longer branch on the lane-mismatch reason"
    )
