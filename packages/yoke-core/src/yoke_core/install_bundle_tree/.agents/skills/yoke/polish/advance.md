# Polish — Advance To Implemented

Covers polish steps 10 through 15: re-run browser QA gates, capture the final summary, advance status, release the claim, emit the final output, and confirm completion.

**Context variables** (set by earlier phases): `ITEM_NUM`, `WORKTREE_PATH`, `WORKTREE_PATHS`.

---

## 10. Inspect Outstanding QA Requirements (read-only)

Before re-running the browser and E2E gates, inspect the outstanding QA evidence so you know exactly which blocking requirements still need passing runs. This is a typed read-only diagnostic — it never mutates `qa_runs` or `qa_requirements`:

```bash
yoke qa gate-summary --item "YOK-$ITEM_NUM" --target implemented
```

Use `--target reviewed-implementation` to scope to verification-phase only; the bare call prints the summary JSON (add `--json` for the full typed envelope). Do not compose raw `qa_requirements` SQL during polish — `qa.gate_summary.run` is the canonical surface and matches the gate semantics in `yoke_core.domain.qa_gates`. The old checkout-local db-router QA summary is operator-debug fallback only, not the agent-facing teaching shape.

## 10b. Re-run Browser QA Gates

After inspecting outstanding requirements, re-run the browser evidence gates against the latest polish commit. This is the final screenshot QA checkpoint before `implemented`.

- Read `.agents/skills/yoke/advance/browser-qa.md` and execute it with target semantics = `implemented`.
- Read `.agents/skills/yoke/advance/project-e2e.md` and execute it with target semantics = `implemented`.
- Treat both gates exactly like advance does: if browser QA, screenshot evaluation, or project E2E fails, do **not** advance status.
- The browser QA run must execute against the current `HEAD` of each changed implementation worktree so the resulting `qa_runs` rows record the branch/SHA for the latest polish commits. For single-worktree items, use `{WORKTREE_PATH}`. For multi-worktree epics, iterate the changed paths from `WORKTREE_PATHS`.

If either gate blocks, leave the item at `polishing-implementation` and report the failure instead of advancing.

## 11. Capture Final Summary

Before status advancement, capture the details you will present after cleanup is finished. Do not emit the success summary yet:

```
## Polish Complete — YOK-{N}

**Worktree:** {WORKTREE_PATH}
**Worktree lanes:** {WORKTREE_PATHS}
**Files changed:** {count} ({list})
**Tests:** {pass/fail/not configured}
**Commit:** {hash or "no changes needed"}

{Brief summary of what was fixed and why}
```

## 12. Advance to implemented

After all polish work is verified complete and tests pass, advance to `implemented`. Use `/yoke advance` so the canonical advance skill runs the polishing-implementation → implemented gate, rebuilds the rendered body, and syncs GitHub.

```bash
/yoke advance "YOK-${ITEM_NUM}" implemented
```

Final output should include:
> **YOK-{N}** polished: `polishing-implementation` -> `implemented`
> The scheduler will route this item to `/yoke usher` for merge and deploy.

`implemented` is a hard handoff point for this command. Do **not** continue into usher, merge, PR creation, or deployment from the polish flow. Any merge/deploy work must begin through an explicit `/yoke usher` command entrypoint.

**If any step above failed or tests are failing:** Do NOT advance to `implemented`. Leave the item at `polishing-implementation` and report the failure.

Function-call equivalent (for dispatch-surface callers — `/yoke advance` builds this envelope internally):

```jsonc
{
  "function": "lifecycle.transition.execute",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "item", "item_id": $ITEM_NUM},
  "intent": "polish_complete",
  "payload": {"source_status": "polishing-implementation", "target_status": "implemented"},
  "options": {"sync_github_body": true}
}
```

## 13. Release Item Claim

Release the exclusive work claim before any success output is emitted. Successful polish is not complete while the session still owns `YOK-${ITEM_NUM}`.

```bash
yoke claims work release \
    --item "YOK-${ITEM_NUM}" \
    --reason completed
```

**Important:** This MUST run before the final operator summary. A release failure surfaces in the CLI output and must still be called out in the final report.

Function-call equivalent (for dispatch-surface callers — the CLI above builds this envelope internally):

```jsonc
{
  "function": "claims.work.release",
  "actor": {"session_id": "<this-session>"},
  "target": {"kind": "claim", "claim_id": <claim_id>},
  "intent": "polish_complete",
  "payload": {"claim_id": <claim_id>, "reason": "completed"}
}
```

## 14. Final Output

After status advancement and claim release, emit:

```
## Polish Complete — YOK-{N}

**Worktree:** {WORKTREE_PATH}
**Worktree lanes:** {WORKTREE_PATHS}
**Files changed:** {count} ({list})
**Tests:** {pass/fail/not configured}
**Commit:** {hash or "no changes needed"}

{Brief summary of what was fixed and why}
```

Include the status transition note from step 12 in this final output.

## 15. Completion

Polish is complete when:
- All changed files have been reviewed against ACs
- Identified issues have been fixed
- Tests pass (or are not configured)
- Changes are committed (or none were needed)
- Status has been advanced to `implemented`
- The item claim has been released with reason `completed`
- The final report names the resolved worktree path or worktree lane set and the verification that ran
- The operator has been shown what changed in the final output
- The polish flow has stopped at `implemented` without invoking usher or merge steps

Polish is NOT complete if:
- The worktree is in a failing test state — fix before reporting
- The operator interrupted with a question — answer it before continuing

Status advancement is handled in step 12. Claim release is handled in step 13, and the final operator output happens in step 14.
