# Shared Tester Dispatch Template

This is the only Tester prompt template. Conduct uses it for sequential,
batch, retry, and simulation-fix dispatches; other implementation flows use
it for item validation. Callers prepare context and select a variant here,
then render one prompt. Do not maintain caller-local prompt copies.

## Dispatch contract

Use `DispatchDescriptor(role="tester")` rendered via
`yoke_core.domain.dispatch_descriptors.render_for_harness(descriptor, harness_id)`.
Conduct's output gate adds `extras=(("model", "opus"),)` after its second
missing verdict. Result markers are `VERDICT: PASS|FAIL` and
`---REFLECTION-START---`.

A Tester validates materialized agent requirements, deliberate implementation
review, or explicitly requested validation. Browser and exploratory missions
use the ordered plan runner's typed dispatch contract instead.

## Required context

Populate these fields before dispatch. Use registered reads; Git remains an
external command. Keep internal item ids separate from public refs and local
task numbers.

1. **Identity and spec:** `yoke items get PREFIX-N spec` supplies the parent
   spec. For generated tasks, also read
   `yoke workflow-item epic-task body-get --epic <epic-id> --task-num <task-num>`.
   Include the task spec and parent context. Include exact `epic-id` and
   `task-num` for the durable review, dependency interface contracts, and
   downstream task bodies needed for path tracing.
2. **Project QA:** read `yoke items get PREFIX-N project` and
   `yoke qa requirement list --item PREFIX-N --json`. Always include the
   Project Test Plan Cases block, even when no plan is attached. Include every
   materialized row with a non-null `plan_id`: case key, method, instructions,
   expected outcome, method configuration, transition, and host baseline.
   Execute the immutable roster with
   `yoke qa plan run --item PREFIX-N --transition <transition>`.
   Do not extract Command shell text and execute it separately.
3. **Lane and changes:** an item with a single implementation lane uses
   `yoke item-worktrees get PREFIX-N --lane-role implementation --field path`
   and `item_worktrees.get` with `payload = {"lane_role": "implementation"}`
   returning `result.worktree.branch` for `single_implementation_lane`.
   For generated tasks, use the task's own worktree branch and registered lane,
   never the parent's primary lane. Include the
   absolute worktree path, main checkout root, changed files, and diff stat.
4. **Diffs:** capture `git -C <worktree> diff main...HEAD` to a temp file.
   Conduct's task diff is `TASK_BASELINE..HEAD`; on retry include
   `ATTEMPT_BASELINE..HEAD`. Inline a diff only at or below 300 lines;
   otherwise include its full stat and capture path. Never truncate with
   `...`. The minimal retry variant includes changed files and capture paths
   without inline diffs. Preserve captures until review/artifact processing
   finishes. Read watcher capture paths from the wrapper, never construct them.
5. **Project commands and environment:** include the caller's resolved Quick,
   Full, E2E, and Smoke commands when present. Read
   `yoke ephemeral-env get <project> <actual-lane-branch> --json` once;
   use `result.environment.url` only for a healthy environment, otherwise
   `none`. Skip the lookup only for projectless items.

## Complete prompt template

Fill the slots below. Omit task-only or retry-only blocks when inapplicable.
For batch dispatch, resolve every slot from that task's context, lane, and
baselines; never reuse a sibling's identifiers or diff.

```text
Validate {public_ref}{if generated task: " task {task_num}"}: {title}

Spec:
{spec_content; generated task spec plus parent context when applicable}

{if generated task:}
Epic DB identifiers (use exactly for review-insert):
epic-id: {epic_id}
task-num: {task_num}
{dependency interface contracts and downstream task bodies}
{caller-provided Active Path Claim Coverage, read-only for validation}

Project Test Plan Cases:
{plan_case_rows or "none attached"}
Execute the immutable roster with:
yoke qa plan run --item {public_ref} --transition {transition}
If it returns awaiting_agent_review (exit 12), immediately execute the
returned typed reviewer dispatch and exact verdict submission contract.

{if resolved project commands are present:}
Project Test Commands:
Quick: {cmd_quick}
Full: {cmd_full}
E2E: {cmd_e2e}
Smoke: {cmd_smoke}
Ephemeral URL: {ephemeral_url}

Worktree: {worktree_path}
Main repo root: {main_root}
Use absolute paths and module invocations. Shell variables do not persist
across tool calls.

Changed files:
{changed_files}
Diff summary:
{diff_stat}

{normal variant: task/full diff inline, or full stat and capture path}
{on implementation retry: attempt diff inline, or full stat and capture path}
Full branch diff: {full_diff_file or exact git command for registered branch}

{minimal output-gate retry variant:}
Your previous invocation produced no parseable verdict. No inline diff is
provided. Read the changed files and captured diffs directly, run the required
checks, and return a deterministic verdict. Keep this prompt under 2000 tokens
excluding the spec; preserve required identity and QA context.

Review the implementation against the spec's acceptance criteria.
Check codebase-reader naming: surfaces describe current function, purpose,
mechanics, or domain role rather than planning provenance.
Run the resolved tests and materialized plan cases. Compare failing test NAMES
between main and the branch for regressions, not just failure counts.

{if generated task:}
Write the review body to a temp file, then persist it with:
yoke workflow-item epic-task review-insert --epic {epic_id} --task-num {task_num} --verdict <pass|fail> --body-file <review-path>
A text verdict alone cannot satisfy Conduct's durable-review gate.

OUTPUT DISCIPLINE: End with VERDICT: PASS or VERDICT: FAIL and a brief summary.
Do not echo the full spec or diff. Include the delimited reflection envelope
required by the Tester agent definition.
```

## Ordered QA review continuation

An `awaiting_agent_review` result is dispatch authority, not evidence of human
review. A `subagent` dispatch uses its returned type, prompt, and immutable
bundle. A `main_agent_mission` stays with the main agent, which sends each typed
walker dispatch to an informed subagent or target-machine session, handles
`HUMAN_GATE` through the Progress Log and operator channel, aggregates the
report, and executes the exact `submit_command`. Submit `undetermined` only
with attached evidence; it halts until the owner resolves the Inbox request.
An unexecuted case records failed/`blocked_on_precondition` and does not ask a
human to review missing evidence.
