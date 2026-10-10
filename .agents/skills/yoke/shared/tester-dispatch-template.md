# Shared Tester Dispatch Template

Use this sole template for Conduct sequential/batch/retry/simulation-fix
dispatches and item validation; callers fill context and select a variant.
Use `DispatchDescriptor(role="tester")` rendered through
`yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`.
Conduct adds `extras=(("model", "opus"),)` after its second missing verdict.
Markers: `VERDICT: PASS|FAIL`, `---REFLECTION-START---`.

Tester handles materialized agent requirements, deliberate implementation
review or explicit validation. Browser/exploratory missions use the ordered
plan runner's typed dispatch.

## Prepare before dispatch

Use registered reads; separate public refs, internal ids and local task numbers.

- Read `yoke items get PREFIX-N spec`; generated tasks also need
  `yoke workflow-item epic-task body-get --epic PREFIX-N --task-num <task-num>`,
  parent context, exact review identity, dependency interfaces and downstream
  bodies for path tracing.
- Read project and `yoke qa requirement list --item PREFIX-N --json`.
  Always fill Project Test Plan Cases, even with none attached. Include each
  materialized non-null-plan row's case key, method, instructions, outcome,
  configuration, transition and host baseline. Use the immutable plan runner;
  Command text is not a separate execution recipe.
- Single implementation lane: `yoke item-worktrees get PREFIX-N --lane-role implementation --field path`;
  `item_worktrees.get` with `payload = {"lane_role": "implementation"}`
  returns `result.worktree.branch` for `single_implementation_lane`.
  Generated tasks use their own registered lane/branch, never the parent lane.
  Include absolute lane/main roots, changed paths and full diff statistics.
- Capture `git -C <worktree> diff main...HEAD`; task diffs use
  `TASK_BASELINE..HEAD`, retries also `ATTEMPT_BASELINE..HEAD`.
  Inline at most 300 lines; otherwise full stat plus capture path, without
  truncation. Minimal retry provides paths instead of inline diffs. Preserve
  captures through review/artifact processing; take watcher paths from the
  wrapper, never construct them.
- Include resolved Quick/Full/E2E/Smoke commands when present. Read
  `yoke ephemeral-env get <project> <actual-lane-branch> --json` once;
  only a healthy `result.environment.url` is usable, otherwise none.
  Only projectless items skip this lookup.

Batch slots belong to each task's own identity, lane and baselines. Omit
inapplicable task/retry blocks, rather than reusing sibling context.

## Complete prompt

```text
Validate {public_ref}{if generated task: " task {task_num}"}: {title}

Spec:
{spec_content; task spec plus parent context when applicable}

{generated task only:}
Review identity (use exactly for review-insert):
epic-id: {epic_ref}
task-num: {task_num}
{dependency interfaces and downstream task bodies}
{caller-provided Active Path Claim Coverage, read-only for validation}

Project Test Plan Cases:
{complete plan-case rows or "none attached"}
Execute the immutable roster:
yoke qa plan run --item {public_ref} --transition {transition}
On awaiting_agent_review (exit 12), immediately execute the returned typed
reviewer dispatch and exact verdict submission contract.

{resolved project commands when present:}
Project Test Commands:
Quick: {cmd_quick}
Full: {cmd_full}
E2E: {cmd_e2e}
Smoke: {cmd_smoke}
Ephemeral URL: {ephemeral_url}

Worktree: {worktree_path}
Main repo root: {main_root}
Use absolute paths/module invocations; shell variables do not persist.

Changed files: {changed_files}
Diff summary: {full diff_stat}
{normal: full/task diff inline <=300 lines, otherwise full stat/capture path}
{implementation retry: attempt diff with the same bound}
Full branch diff: {full_diff_file or exact git command for registered branch}

{minimal output-gate retry only:}
Previous invocation had no parseable verdict. Read changed files/captured diffs,
run required checks and return a deterministic verdict. No inline diff.
Keep this prompt under 2000 tokens excluding spec; retain identity and QA.

Review all acceptance criteria and codebase-reader naming: current function,
purpose/mechanics/domain role, free of planning provenance. Execute resolved
tests and materialized cases. Compare failing test NAMES on main and branch
for regressions, rather than counts.

{generated task only:}
Write the review body to a temp file, then persist:
yoke workflow-item epic-task review-insert --epic {epic_ref} --task-num {task_num} --verdict <pass|fail> --body-file <review-path>
Text alone does not satisfy Conduct's durable-review gate.

End with VERDICT: PASS or VERDICT: FAIL and a brief summary.
Do not echo full spec/diff. Include the Tester definition's delimited reflection
envelope.
```

## Ordered QA review continuation

`awaiting_agent_review` grants dispatch authority, rather than human-review
proof. A `subagent` uses returned type, prompt and immutable bundle.
A `main_agent_mission` remains with the main agent, which dispatches typed
walkers to informed subagents or target-machine sessions. For `HUMAN_GATE`,
record action/resume state in Progress Log and send to live covering steering
(`yoke say --steering`); `awaiting_seat` or no covering seat routes to human
`items.owner` (`yoke say --actor`). Walkers never send Fleet mail.
`--item` returns the answer to the current holder.

Aggregate and execute the exact `submit_command`. Submit `undetermined` only
with attached evidence; it halts until the owner resolves Inbox review.
An unexecuted case records failed/`blocked_on_precondition`, without asking
for human review of missing evidence.
